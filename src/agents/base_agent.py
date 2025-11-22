import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from dotenv import load_dotenv
from pydantic import ValidationError

from config.settings import get_agent_config
from src.communication import get_async_redis_connection, get_groq_client
from src.typing import BaseAgentResponse, BaseMessage, BaseSchema

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        agent_type: str,
    ):
        self.agent_type = agent_type
        self.config = get_agent_config(self.agent_type)

        self._redis_manager = get_async_redis_connection()
        self.redis = self._redis_manager.client

        self._llm_manager = get_groq_client()
        self.llm = self._llm_manager.get_client()

    async def _call_llm(
        self,
        query_id: Optional[str],
        conversation_id: Optional[str],
        messages: List[Dict[str, str]],
        response_schema: Optional[Type[BaseSchema]] = None,
        response_model: Optional[Type[BaseAgentResponse]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> BaseAgentResponse:
        if not self.llm:
            raise ValueError("No Groq API key provided")
        try:
            response_format = None
            if response_schema and not tools:
                schema = response_schema.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": schema},
                }

            llm_params = self.config.get_llm_params()

            call_kwargs = {
                **llm_params,
                "messages": messages,
                "response_format": response_format,
            }

            if tools:
                call_kwargs["tools"] = tools

            response = await self.llm.chat.completions.create(**call_kwargs)

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

            # Handle schema validation if response_schema is provided
            if response_schema:
                try:
                    data = json.loads(content) if content else {}

                    if isinstance(data, list):
                        if len(data) == 1 and isinstance(data[0], dict):
                            data = data[0]
                        else:
                            raise ValidationError(f"Invalid array structure: {data}")

                    llm_response_schema = response_schema.model_validate(data)

                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"Schema validation failed: {e}")
                    raise
            elif tools:
                # When tools are provided, extract tool_calls from message
                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    # Tool calls are available in message.tool_calls
                    llm_response_schema = {
                        "tool_calls": tool_calls,
                        "content": content,
                    }
                    logger.debug(
                        f"Extracted {len(tool_calls)} tool calls from response"
                    )
                else:
                    # No tool calls, just return content
                    llm_response_schema = {
                        "tool_calls": [],
                        "content": content,
                    }
            else:
                # No response_schema and no tools: return plain text response
                llm_response_schema = content

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
