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

load_dotenv()

logger = logging.getLogger(__name__)

# Debug directory for LLM responses
DEBUG_DIR = Path("debug_llm_responses")
LLM_CALL_MAX_RETRIES = 3
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

        logger.info(
            f"{self.agent_type}: Subscribed to approval channel, now broadcasting request for '{tool_name}' "
            f"(approval_id: {approval_request.approval_id}, timeout: {hitl.timeout_seconds}s)"
        )

        # Broadcast to frontend AFTER subscribing
        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.APPROVAL_REQUIRED,
            approval_request.model_dump(),
        )

        logger.info(
            f"{self.agent_type}: Waiting for approval on '{tool_name}' "
            f"(approval_id: {approval_request.approval_id})"
        )

        # Wait for response
        try:
            async with asyncio.timeout(hitl.timeout_seconds):
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue

                    logger.debug(
                        f"{self.agent_type}: Received message on approval channel: {message['data'][:100]}..."
                    )

                    try:
                        response = ApprovalResponse.model_validate_json(message["data"])

                        # Match approval_id to handle multiple pending approvals
                        if response.approval_id == approval_request.approval_id:
                            logger.info(
                                f"{self.agent_type}: ✅ Received matching approval response: "
                                f"{response.action.value} for '{tool_name}' (approval_id: {response.approval_id})"
                            )

                            # Broadcast resolution
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
                        else:
                            logger.debug(
                                f"{self.agent_type}: Received approval for different request: "
                                f"{response.approval_id} (expected: {approval_request.approval_id})"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Invalid approval response: {e}, data: {message['data']}"
                        )
                        continue

        except asyncio.TimeoutError:
            logger.warning(
                f"{self.agent_type}: Approval timeout for '{tool_name}' "
                f"after {hitl.timeout_seconds}s"
            )
            return ApprovalResponse(
                approval_id=approval_request.approval_id,
                query_id=query_id,
                action=ApprovalAction.REJECT,
                reason="Approval timeout - no response received",
            )
        finally:
            await pubsub.unsubscribe(response_channel)

    # ============= Debug & LLM Methods =============

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

                response = None
                for attempt in range(1, LLM_CALL_MAX_RETRIES + 1):
                    try:
                        response = await self.llm.chat.completions.create(**call_kwargs)
                        break
                    except Exception as call_error:
                        logger.warning(
                            f"{self.agent_type}: LLM call failed (attempt {attempt}/{LLM_CALL_MAX_RETRIES}): {call_error}"
                        )
                        if attempt == LLM_CALL_MAX_RETRIES:
                            logger.error(f"{self.agent_type}: Exhausted LLM retries")
                            raise
                        await asyncio.sleep(LLM_CALL_RETRY_DELAY)
                assert response is not None  # For mypy guard

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

                # Broadcast reasoning if available
                if llm_reasoning and query_id:
                    from src.typing.redis.constants import MessageType

                    await self.publish_broadcast(
                        RedisChannels.get_query_updates_channel(query_id),
                        MessageType.THINKING,
                        {
                            "reasoning": llm_reasoning,
                            "agent_type": self.agent_type,
                        },
                    )

                # If LLM wants to call tools, execute them and continue the loop
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
                    # Continue loop - let LLM process tool results
                    continue

                # Only break when LLM is done (finish_reason == "stop")
                if choice.finish_reason == "stop":
                    break

                # For other finish reasons (length, etc.), also break but log warning
                logger.warning(
                    f"LLM finished with reason: {choice.finish_reason}, breaking loop"
                )
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
        except Exception as e:
            logger.error(f"Broadcast publish failed for {channel}: {e}")

    @abstractmethod
    async def start(self):
        """Start the agent. Must be implemented by subclasses."""
        pass
