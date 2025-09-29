import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

import redis.asyncio as redis
from config.settings import DEFAULT_CONFIGS, AgentConfig
from dotenv import load_dotenv
from groq import AsyncGroq
from jsonschema import ValidationError

from src.typing import BaseAgentRequest, BaseAgentResponse, BaseSchema

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        prompt: str = None,
        llm_api_key: str = None,
        llm_model: str = "llama-3.3-70b-versatile",
    ):
        self.name = name
        self.redis = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )
        self.channel = "agent_channel"
        self.prompt = None
        self.llm_api_key = llm_api_key or os.environ.get("GROQ_API_KEY")
        self.llm_model = llm_model
        self.config = DEFAULT_CONFIGS.get(self.name, AgentConfig())
        self.llm = AsyncGroq(api_key=self.llm_api_key) if self.llm_api_key else None

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        response_schema: Optional[Type[BaseSchema]] = None,
        response_model: Optional[Type[BaseAgentResponse]] = None,
    ) -> Any:
        if not self.llm:
            raise ValueError("No Groq API key provided")
        try:
            response_format = None
            if response_schema:
                schema = response_schema.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": schema},
                }
            response = await self.llm.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                response_format=response_format,
            )
            logger.debug("LLM raw response: %s", response)
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            content = (
                message.content.strip() if getattr(message, "content", None) else None
            )
            llm_reasoning = getattr(message, "reasoning", None)

            raw_usage = getattr(response, "usage", None)
            if raw_usage:
                llm_usage = {
                    "completion_tokens": getattr(raw_usage, "completion_tokens", None),
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
                    "total_tokens": getattr(raw_usage, "total_tokens", None),
                    "completion_time": getattr(raw_usage, "completion_time", None),
                    "prompt_time": getattr(raw_usage, "prompt_time", None),
                    "queue_time": getattr(raw_usage, "queue_time", None),
                    "total_time": getattr(raw_usage, "total_time", None),
                }
            else:
                llm_usage = None

            if response_model:
                try:
                    data = json.loads(content) if content else {}
                    parsed = response_model.model_validate(data)
                    if hasattr(parsed, "llm_usage"):
                        parsed.llm_usage = llm_usage
                    if hasattr(parsed, "llm_reasoning"):
                        parsed.llm_reasoning = llm_reasoning
                    return parsed
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.exception("LLM parsing/validation error: %s", e)
                    debug = BaseAgentResponse()
                    debug.llm_usage = llm_usage
                    debug.llm_reasoning = llm_reasoning
                    debug.error = str(e) if hasattr(debug, "error") else None
                    return debug
        except Exception as e:
            logger.exception("LLM call failed: %s", e)
            return "LLM error: Unable to generate response"

    @abstractmethod
    async def process(self, request: BaseAgentRequest) -> BaseAgentResponse:
        pass

    async def communicate(
        self,
        data: Dict[str, Any],
        recipient: str,
        query_id: str,
        action: str = "data_ready",
    ):
        try:
            TIME_TO_LIVE = 3600  # 1 hour
            key = f"query:{query_id}:{recipient}_data"
            await self.redis.setex(key, TIME_TO_LIVE, json.dumps(data))
            message = {
                "from": self.name,
                "to": recipient,
                "query_id": query_id,
                "data_key": key,
                "action": action,
                "timestamp": asyncio.get_event_loop().time(),
            }
            await self.redis.publish(self.channel, json.dumps(message))
        except redis.RedisError as e:
            logger.error("Redis error in communicate: %s", e)

    async def receive(
        self, query_id: str, timeout: int = 30
    ) -> Optional[Dict[str, Any]]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            async with asyncio.timeout(timeout):
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        if (
                            data.get("to") == self.name
                            and data.get("query_id") == query_id
                        ):
                            stored_data = await self.get_context(
                                data["data_key"], query_id
                            )
                            return stored_data
        except asyncio.TimeoutError:
            logger.warning(
                "%s timed out waiting for message [Query %s]", self.name, query_id
            )
        except redis.RedisError as e:
            logger.error("Redis error in receive: %s", e)
        finally:
            await pubsub.unsubscribe(self.channel)
        return None

    async def listen_continuously(self, query_id: str):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("to") == self.name and data.get("query_id") == query_id:
                        stored_data = await self.get_context(data["data_key"], query_id)
                        logger.info(
                            "%s continuous listen for Query %s: %s",
                            self.name,
                            query_id,
                            stored_data,
                        )
                        if data.get("action") == "retry":
                            await self.process(data.get("retry_query", ""), query_id)
        except redis.RedisError as e:
            logger.error("Redis error in listen_continuously: %s", e)
        finally:
            await pubsub.unsubscribe(self.channel)

    async def get_context(self, key: str, query_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = await self.redis.get(key)
            return json.loads(data) if data else None
        except redis.RedisError as e:
            logger.error("Redis error in get_context: %s", e)
            return None
