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

from src.typing import BaseAgentResponse, BaseSchema
from src.typing.redis import CommandMessage, QueryTask, SharedData, TaskUpdate

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        llm_api_key: str = None,
        llm_model: str = "llama-3.3-70b-versatile",
    ):
        self.name = name
        self.redis = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )
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
    async def get_pub_channels(self) -> List[str]:
        """Return list of channels this agent publishes to."""
        pass

    @abstractmethod
    async def get_sub_channels(self) -> List[str]:
        """Return list of channels this agent subscribes to."""
        pass

    @abstractmethod
    async def handle_message(self, channel: str, message: Dict[str, Any]):
        """Handle incoming message on a channel."""
        pass

    @abstractmethod
    async def process(self, request) -> Any:
        """Process a request and return a response. Must be implemented by subclasses."""
        pass

    async def listen_channels(self):
        """Listen to all subscribed channels and dispatch incoming messages to handle_message."""
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)
        logger.info(f"{self.name} listening on {channels}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    # Validate based on channel
                    channel = message["channel"]
                    if channel.startswith("agent:task_updates"):
                        validated = TaskUpdate(**data)
                    elif channel.startswith("agent:command_channel"):
                        validated = CommandMessage(**data)
                    elif channel == "agent:query_channel":
                        validated = QueryTask(**data)
                    else:
                        validated = data  # Fallback
                    await self.handle_message(
                        channel=channel,
                        message=validated.model_dump()
                        if hasattr(validated, "model_dump")
                        else validated,
                    )
        except redis.RedisError as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def publish_message(self, channel: str, message: Dict[str, Any]):
        """Publish message to a channel, validated with Pydantic."""
        # Determine model based on channel
        if channel.startswith("agent:task_updates"):
            model = TaskUpdate
        elif channel.startswith("agent:command_channel"):
            model = CommandMessage
        elif channel == "agent:query_channel":
            model = QueryTask
        else:
            model = None
        if model:
            validated = model(**message)
            await self.redis.publish(
                channel=channel, message=validated.model_dump_json()
            )
        else:
            await self.redis.publish(channel=channel, message=json.dumps(message))
        logger.info(f"{self.name} published on {channel}: {message}")

    async def update_shared_data(self, query_id: str, updates: Dict[str, Any]):
        """Update shared data as JSON in agent:shared_data:{query_id}, validated with Pydantic"""
        key = f"agent:shared_data:{query_id}"
        # Get current data
        current_data = await self.redis.get(key)
        data = json.loads(current_data) if current_data else {}
        # Merge updates
        self._deep_update(data, updates)
        # Validate with Pydantic
        validated = SharedData(**data)
        # Set back as JSON
        await self.redis.set(key, validated.model_dump_json())
        logger.debug(f"Updated shared data for {query_id}: {updates}")

    def _deep_update(self, base: Dict, updates: Dict):
        """Deep merge updates into base dict, handle list append for agents_done."""
        for key, value in updates.items():
            if (
                key == "agents_done"
                and isinstance(value, list)
                and key in base
                and isinstance(base[key], list)
            ):
                # Append unique items
                for item in value:
                    if item not in base[key]:
                        base[key].append(item)
            elif (
                isinstance(value, dict) and key in base and isinstance(base[key], dict)
            ):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    @abstractmethod
    async def start(self):
        """Start the agent. Must be implemented by subclasses."""
        pass
