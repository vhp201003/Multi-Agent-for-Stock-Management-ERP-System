import asyncio
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
from src.typing.approval import ApprovalAction, ApprovalRequest, ApprovalResponse
from src.typing.mcp.base import HITLMetadata
from src.typing.redis.constants import MessageType, RedisChannels
from src.typing.redis.shared_data import LLMUsage
from src.utils.shared_data_utils import update_shared_data_field

load_dotenv()
logger = logging.getLogger(__name__)
# Debug directory for LLM responses
DEBUG_DIR = Path("debug_llm_responses")
LLM_CALL_MAX_RETRIES = 5
LLM_CALL_RETRY_DELAY = 0.5


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

        # HITL: Store tool approval configs (populated by subclasses)
        self._tools_hitl_metadata: Dict[str, HITLMetadata] = {}

    # ============= HITL: Approval Methods =============

    def register_tool_hitl(self, tool_name: str, hitl: HITLMetadata) -> None:
        """Register HITL metadata for a tool (called during init)."""
        self._tools_hitl_metadata[tool_name] = hitl

    def get_tool_hitl(self, tool_name: str) -> Optional[HITLMetadata]:
        """Get HITL metadata for a tool."""
        return self._tools_hitl_metadata.get(tool_name)

    def tool_requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires human approval."""
        hitl = self._tools_hitl_metadata.get(tool_name)
        return hitl.requires_approval if hitl else False

    async def request_approval(
        self,
        query_id: str,
        tool_name: str,
        proposed_params: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> ApprovalResponse:
        """
        Request human approval for a tool execution.

        Publishes approval request to frontend and waits for response.
        Blocks until user responds or timeout.

        Returns:
            ApprovalResponse with user's decision (approve/modify/reject)
        """
        hitl = self.get_tool_hitl(tool_name)
        if not hitl or not hitl.requires_approval:
            # No approval needed - auto approve
            return ApprovalResponse(
                approval_id="auto",
                query_id=query_id,
                action=ApprovalAction.APPROVE,
            )

        # Build approval request
        approval_request = ApprovalRequest(
            query_id=query_id,
            task_id=task_id,
            agent_type=self.agent_type,
            tool_name=tool_name,
            proposed_params=proposed_params,
            title=hitl.approval_message or f"Approve {tool_name}?",
            description=f"Tool '{tool_name}' requires your approval before execution.",
            modifiable_fields=hitl.modifiable_fields,
            timeout_seconds=hitl.timeout_seconds,
        )

        # Subscribe to response channel FIRST to avoid race condition
        response_channel = RedisChannels.get_approval_response_channel(query_id)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(response_channel)

        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.APPROVAL_REQUIRED,
            approval_request.model_dump(),
        )

        # Wait for response
        try:
            async with asyncio.timeout(hitl.timeout_seconds):
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue

                    try:
                        response = ApprovalResponse.model_validate_json(message["data"])

                        # Match approval_id to handle multiple pending approvals
                        if response.approval_id == approval_request.approval_id:
                            await self.publish_broadcast(
                                RedisChannels.get_query_updates_channel(query_id),
                                MessageType.APPROVAL_RESOLVED,
                                {
                                    "approval_id": approval_request.approval_id,
                                    "action": response.action.value,
                                    "tool_name": tool_name,
                                },
                            )
                            return response
                    except Exception:
                        continue

        except asyncio.TimeoutError:
            return ApprovalResponse(
                approval_id=approval_request.approval_id,
                query_id=query_id,
                action=ApprovalAction.REJECT,
                reason="Approval timeout - no response received",
            )
        finally:
            await pubsub.unsubscribe(response_channel)

    # ============= Debug & LLM Methods =============

    def save_llm_response_debug(
        self, query_id: str, response_data: Dict[str, Any]
    ) -> None:
        try:
            query_dir = DEBUG_DIR / self.agent_type / query_id
            query_dir.mkdir(parents=True, exist_ok=True)

            import time

            timestamp = int(time.time() * 1000)
            debug_file = query_dir / f"{timestamp}.json"
            with open(debug_file, "w") as f:
                json.dump(response_data, f, indent=2, default=str)
        except Exception:
            pass

    def build_llm_call_kwargs(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]],
        response_schema: Optional[Type[BaseSchema]],
        tool_choice: Optional[str],
    ) -> Dict[str, Any]:
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

        return call_kwargs

    def extract_llm_usage(self, response: Any) -> Optional[Dict[str, Any]]:
        raw_usage = getattr(response, "usage", None)
        if not raw_usage:
            return None

        return {
            "completion_tokens": getattr(raw_usage, "completion_tokens", None),
            "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
            "total_tokens": getattr(raw_usage, "total_tokens", None),
            "completion_time": getattr(raw_usage, "completion_time", None),
            "prompt_time": getattr(raw_usage, "prompt_time", None),
            "queue_time": getattr(raw_usage, "queue_time", None),
            "total_time": getattr(raw_usage, "total_time", None),
        }

    async def accumulate_llm_usage(
        self, query_id: str, llm_usage: Dict[str, Any]
    ) -> None:
        try:
            usage_key = f"{self.agent_type}"
            json_path = f".llm_usage.{usage_key}"

            from src.utils.shared_data_utils import get_shared_data_field

            existing_usage = await get_shared_data_field(
                self.redis, query_id, json_path
            )

            if existing_usage and isinstance(existing_usage, (dict, list)):
                # Handle Redis JSON returning list
                if isinstance(existing_usage, list) and len(existing_usage) > 0:
                    existing_usage = existing_usage[0]

                if isinstance(existing_usage, dict):
                    # Accumulate numeric fields
                    llm_usage = {
                        "completion_tokens": (
                            existing_usage.get("completion_tokens") or 0
                        )
                        + (llm_usage.get("completion_tokens") or 0),
                        "prompt_tokens": (existing_usage.get("prompt_tokens") or 0)
                        + (llm_usage.get("prompt_tokens") or 0),
                        "total_tokens": (existing_usage.get("total_tokens") or 0)
                        + (llm_usage.get("total_tokens") or 0),
                        "completion_time": (existing_usage.get("completion_time") or 0)
                        + (llm_usage.get("completion_time") or 0),
                        "prompt_time": (existing_usage.get("prompt_time") or 0)
                        + (llm_usage.get("prompt_time") or 0),
                        "queue_time": (existing_usage.get("queue_time") or 0)
                        + (llm_usage.get("queue_time") or 0),
                        "total_time": (existing_usage.get("total_time") or 0)
                        + (llm_usage.get("total_time") or 0),
                    }

            usage_obj = LLMUsage(**llm_usage)
            await update_shared_data_field(
                self.redis, query_id, json_path, usage_obj.model_dump()
            )
        except Exception:
            pass

    async def broadcast_reasoning(self, query_id: str, llm_reasoning: str) -> None:
        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.THINKING,
            {
                "reasoning": llm_reasoning,
                "agent_type": self.agent_type,
            },
        )

    async def call_llm(
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
            call_kwargs = self.build_llm_call_kwargs(
                messages, tools, response_schema, tool_choice
            )

            # --- ReAct Loop ---
            turn_count = 0
            MAX_TURNS = 10
            llm_reasoning = None

            while True:
                turn_count += 1
                if turn_count > MAX_TURNS:
                    break

                response = None
                parsed_result = None

                # Retry loop for both LLM call AND validation
                for attempt in range(1, LLM_CALL_MAX_RETRIES + 1):
                    try:
                        response = await self.llm.chat.completions.create(**call_kwargs)

                        choice = response.choices[0]
                        message = choice.message
                        content = message.content

                        if response_schema and not message.tool_calls:
                            parsed_result = response_schema.model_validate_json(content)

                        break

                    except (json.JSONDecodeError, ValidationError) as e:
                        if attempt < LLM_CALL_MAX_RETRIES:
                            error_msg = (
                                f"Your previous response had invalid format. "
                                f"Error: {str(e)[:200]}. "
                                f"Please provide a valid JSON response matching the schema."
                            )
                            messages.append({"role": "user", "content": error_msg})
                            call_kwargs["messages"] = messages
                            await asyncio.sleep(LLM_CALL_RETRY_DELAY)
                            continue
                        raise  # Raise after exhausting retries

                    except Exception as e:
                        logger.error(f"LLM call failed: {e}")
                        if attempt < LLM_CALL_MAX_RETRIES:
                            await asyncio.sleep(LLM_CALL_RETRY_DELAY)
                            continue
                        raise RuntimeError(
                            f"LLM call failed after {LLM_CALL_MAX_RETRIES} retries: {e}"
                        ) from e

                assert response is not None

                if query_id:
                    self.save_llm_response_debug(query_id, response.model_dump())

                choice = response.choices[0]
                message = choice.message
                content = message.content
                tool_calls = message.tool_calls

                turn_usage = self.extract_llm_usage(response)
                if turn_usage:
                    if query_id:
                        await self.accumulate_llm_usage(query_id, turn_usage)

                llm_reasoning = getattr(message, "reasoning", None)
                if llm_reasoning and query_id:
                    await self.broadcast_reasoning(query_id, llm_reasoning)

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

                if choice.finish_reason == "stop":
                    break

                break

            result = parsed_result if parsed_result is not None else content

            return result

        except Exception:
            raise

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

    async def publish_channel(
        self, channel: str, message: Any, message_type: Type[BaseMessage]
    ):
        try:
            if not isinstance(message, message_type):
                message = message_type.model_validate(message)

            await self.redis.publish(channel, message.model_dump_json())

        except Exception:
            pass

    async def publish_broadcast(
        self,
        channel: str,
        message_type: str,  # MessageType enum value
        data: Dict[str, Any],
    ):
        """Publish a structured broadcast message."""
        try:
            from src.typing.redis.constants import BroadcastMessage

            message = BroadcastMessage(type=message_type, data=data)
            await self.redis.publish(channel, message.model_dump_json())
        except Exception:
            pass

    async def broadcast_tool_result(
        self, query_id: str, tool_name: str, parameters: Dict, result: Dict
    ):
        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.TOOL_EXECUTION,
            {
                "tool_name": tool_name,
                "parameters": parameters,
                "result": result,
                "agent_type": self.agent_type,
            },
        )

    async def broadcast_error(self, query_id: str, error_msg: str):
        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.ERROR,
            {"error": error_msg, "agent_type": self.agent_type},
        )

    @abstractmethod
    async def start(self):
        """Start the agent. Must be implemented by subclasses."""
        pass
