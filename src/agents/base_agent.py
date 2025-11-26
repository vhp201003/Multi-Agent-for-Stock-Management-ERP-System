import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Type

from dotenv import load_dotenv
from pydantic import ValidationError

from config.settings import get_agent_config
from src.communication import get_async_redis_connection, get_groq_client
from src.typing import BaseMessage, BaseSchema

load_dotenv()

logger = logging.getLogger(__name__)

# Debug directory for LLM responses
DEBUG_DIR = Path("debug_llm_responses")


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

    def _save_llm_response_debug(
        self, query_id: str, response_data: Dict[str, Any]
    ) -> None:
        try:
            agent_dir = DEBUG_DIR / self.agent_type
            agent_dir.mkdir(parents=True, exist_ok=True)

            debug_file = agent_dir / f"{query_id}.json"
            with open(debug_file, "w") as f:
                json.dump(response_data, f, indent=2, default=str)

            logger.debug(f"Saved LLM response debug to {debug_file}")
        except Exception as e:
            logger.warning(f"Failed to save debug response: {e}")

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        query_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_schema: Optional[Type[BaseSchema]] = None,
        tool_choice: Optional[str] = "auto",
        tool_executor: Optional[Callable[[List[Dict]], Awaitable[List[Dict]]]] = None,
    ) -> Tuple[Any, Optional[Dict[str, Any]], Optional[str]]:
        if not self.llm:
            raise ValueError("No Groq API key provided")

        try:
            llm_params = self.config.get_llm_params()

            call_kwargs = {
                **llm_params,
                "messages": messages,
            }

            if tools:
                call_kwargs["tools"] = tools
                call_kwargs["tool_choice"] = tool_choice

            if response_schema and not tools:
                call_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema.__name__,
                        "schema": response_schema.model_json_schema(),
                    },
                }

            # --- ReAct Loop ---
            turn_count = 0
            MAX_TURNS = 10
            while True:
                turn_count += 1
                if turn_count > MAX_TURNS:
                    logger.warning(f"ReAct loop exceeded max turns ({MAX_TURNS})")
                    break

                response = await self.llm.chat.completions.create(**call_kwargs)

                # Debug logging
                if query_id:
                    self._save_llm_response_debug(query_id, response.model_dump())

                choice = response.choices[0]
                message = choice.message
                content = message.content
                tool_calls = message.tool_calls

                raw_usage = getattr(response, "usage", None)
                llm_usage = None
                if raw_usage:
                    llm_usage = {
                        "completion_tokens": getattr(
                            raw_usage, "completion_tokens", None
                        ),
                        "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
                        "total_tokens": getattr(raw_usage, "total_tokens", None),
                        "completion_time": getattr(raw_usage, "completion_time", None),
                        "prompt_time": getattr(raw_usage, "prompt_time", None),
                        "queue_time": getattr(raw_usage, "queue_time", None),
                        "total_time": getattr(raw_usage, "total_time", None),
                    }

                llm_reasoning = getattr(message, "reasoning", None)

                if tool_calls and tools and tool_executor:
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [t.model_dump() for t in tool_calls]
                        if tool_calls
                        else None,
                    }
                    messages.append(assistant_msg)

                    tool_results = await tool_executor(tool_calls)

                    for tool_result in tool_results:
                        messages.append(tool_result)

                    call_kwargs["messages"] = messages
                    continue

                break

            result = content

            if response_schema:
                try:
                    data = json.loads(content) if content else {}
                    if (
                        isinstance(data, list)
                        and len(data) == 1
                        and isinstance(data[0], dict)
                    ):
                        data = data[0]
                    result = response_schema.model_validate(data)
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.error(f"Schema validation failed: {e}")
                    raise

            if tools and tool_calls and not tool_executor:
                result = {
                    "tool_calls": [t.model_dump() for t in tool_calls],
                    "content": content,
                }

            return result, llm_usage, llm_reasoning

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
