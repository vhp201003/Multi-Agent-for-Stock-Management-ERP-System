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

from src.typing import BaseAgentResponse, BaseMessage, BaseSchema

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        agent_type: str,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        llm_api_key: str = None,
        llm_model: str = "llama-3.3-70b-versatile",
    ):
        self.agent_type = agent_type
        self.redis = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )
        self.llm_api_key = llm_api_key or os.environ.get("GROQ_API_KEY")
        self.llm_model = llm_model
        self.config = DEFAULT_CONFIGS.get(self.agent_type, AgentConfig())
        self.llm = AsyncGroq(api_key=self.llm_api_key) if self.llm_api_key else None

    async def _call_llm(
        self,
        query_id: Optional[str],
        conversation_id: Optional[str],
        messages: List[Dict[str, str]],
        response_schema: Optional[Type[BaseSchema]] = None,
        response_model: Optional[Type[BaseAgentResponse]] = None,
    ) -> BaseAgentResponse:
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

            llm_response_schema = None

            if response_schema:
                try:
                    data = json.loads(content) if content else {}
                    logger.info(f"Raw LLM data before validation: {data}")
                    llm_response_schema = response_schema.model_validate(data)

                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"LLM parsing/validation error: {e}")
                    logger.error(f"Raw LLM content: {content}")
                    logger.error(
                        f"Parsed data: {data if 'data' in locals() else 'Failed to parse'}"
                    )
                    raise

                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"LLM parsing/validation error (duplicate): {e}")
                    logger.error(f"Raw LLM content: {content}")
                    raise

            if response_model:
                result = response_model(
                    query_id=query_id,
                    conversation_id=conversation_id,
                    llm_usage=llm_usage,
                    llm_reasoning=llm_reasoning,
                    result=llm_response_schema,
                )

                return result

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    @abstractmethod
    async def get_sub_channels(self) -> List[str]:
        pass

    @abstractmethod
    async def process(self, request) -> Any:
        """Process a request and return a response.

        Core business logic method that all agents must implement:
        - OrchestratorAgent: LLM-based query decomposition and coordination
        - WorkerAgent: Domain-specific task execution with MCP tools

        Args:
            request: Agent-specific request object

        Returns:
            Agent-specific response object
        """
        pass

    @abstractmethod
    async def listen_channels(self):
        """Listen to subscribed channels and process messages.

        Each agent implements channel-specific listening logic:
        - OrchestratorAgent: Listens for task updates and workflow coordination
        - WorkerAgent: Listens for execution commands

        Must handle message parsing, validation, and dispatch to update_shared_data_from_message.
        """
        pass

    async def publish_channel(
        self, channel: str, message: Any, message_type: Type[BaseMessage]
    ):
        try:
            if not isinstance(message, message_type):
                message = message_type.model_validate(message)

            await self.redis.publish(channel, message.model_dump_json())

        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")

    @abstractmethod
    async def start(self):
        """Start the agent. Must be implemented by subclasses."""
        pass
