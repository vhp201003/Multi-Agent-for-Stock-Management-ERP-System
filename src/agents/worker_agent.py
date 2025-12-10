import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from toon import encode

from config.prompts.worker import build_worker_agent_prompt
from config.settings import get_agent_config
from src.agents.registry import register_agent, unregister_agent
from src.mcp.client import MCPClient
from src.typing import (
    ResourceCallResponse,
    ToolCallResultResponse,
    WorkerAgentProcessResponse,
)
from src.typing.approval import ApprovalAction
from src.typing.redis import (
    AgentStatus,
    CommandMessage,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskQueueItem,
    TaskStatus,
    TaskUpdate,
)
from src.typing.redis.constants import MessageType
from src.utils.converstation import get_summary_conversation
from src.utils.shared_data_utils import (
    find_task_id,
    get_dependency_context,
    get_shared_data,
    update_shared_data,
)

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    def __init__(
        self,
        agent_type: str,
        agent_description: str,
        instance_id: Optional[str] = None,
        mcp_timeout: float = 30.0,
        examples: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(agent_type, **kwargs)
        self.instance_id = instance_id or str(uuid.uuid4())[:8]
        self.agent_description = agent_description
        self.mcp_server_url = get_agent_config(agent_type).mcp_server_url
        self.mcp_timeout = mcp_timeout
        self.prompt: Optional[str] = None
        self.mcp_client: Optional[MCPClient] = None
        self.examples = examples

        # HITL: Track current query_id for approval requests
        self._current_query_id: Optional[str] = None
        self._current_task_id: Optional[str] = None

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def process(
        self, command_message: CommandMessage
    ) -> WorkerAgentProcessResponse:
        ### Phase 1: Load conversation and prepare messages
        sub_query = command_message.sub_query
        conversation_id = command_message.conversation_id

        # HITL: Store current query context for approval requests
        self._current_query_id = command_message.query_id
        self._current_task_id = await find_task_id(
            self.redis, command_message.query_id, self.agent_type, sub_query
        )

        # Get conversation summary
        summary = await get_summary_conversation(self.redis, conversation_id)

        # Get dependency results from SharedData
        dependency_context = None
        if self._current_task_id:
            dependency_context = await get_dependency_context(
                self.redis, command_message.query_id, self._current_task_id
            )

        messages = [
            {
                "role": "system",
                "content": self.prompt,
            },
            {
                "role": "assistant",
                "content": f"Conversation Summary: {summary}"
                if summary
                else "Conversation Summary: No prior context",
            },
        ]

        # Inject dependency results if available
        if dependency_context:
            logger.debug(
                f"{self.agent_type}[{self.instance_id}]: Loaded dependency context for task {self._current_task_id}"
            )
            logger.debug(f"Dependency Context: {dependency_context}")
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Previous task results (use this data for your analysis):\n{dependency_context}",
                }
            )

        messages.append(
            {
                "role": "user",
                "content": sub_query,
            }
        )

        ### Phase 2: Call LLM to get tool calls from Groq tool_calls
        groq_tools = None
        if hasattr(self, "_mcp_tools_for_groq"):
            groq_tools = self._mcp_tools_for_groq

        # Initialize result object
        worker_process_result = WorkerAgentProcessResponse()
        worker_process_result.query_id = command_message.query_id
        worker_process_result.conversation_id = command_message.conversation_id

        # Define tool executor for ReAct loop
        async def tool_executor(tool_calls: List[Any]) -> List[Dict[str, Any]]:
            return await self._execute_tools(
                tool_calls,
                worker_process_result.tools_result,
                worker_process_result.query_id,
            )

        # Call LLM with ReAct loop
        result, llm_usage, llm_reasoning = await self._call_llm(
            query_id=command_message.query_id,
            messages=messages,
            tools=groq_tools,
            tool_executor=tool_executor,
        )

        worker_process_result.llm_reasoning = llm_reasoning
        worker_process_result.llm_usage = llm_usage

        if isinstance(result, str):
            logger.debug(f"{self.agent_type}: Final LLM response: {result}")

        return worker_process_result

    async def _execute_tools(
        self,
        tool_calls: List[Any],
        tools_result_accumulator: List[ToolCallResultResponse],
        query_id: str,
    ) -> List[Dict[str, Any]]:
        """Execute tool calls and return results for LLM context."""
        results = []
        for tool_call in tool_calls:
            result = await self._execute_single_tool(
                tool_call, tools_result_accumulator, query_id
            )
            results.append(result)
        return results

    async def _execute_single_tool(
        self,
        tool_call: Any,
        accumulator: List[ToolCallResultResponse],
        query_id: str,
    ) -> Dict[str, Any]:
        """Execute a single tool call with HITL check."""
        try:
            tool_name = tool_call.function.name
            parameters = (
                json.loads(tool_call.function.arguments)
                if isinstance(tool_call.function.arguments, str)
                else tool_call.function.arguments
            )

            # HITL approval check
            if self.tool_requires_approval(tool_name):
                approval = await self.request_approval(
                    query_id=query_id,
                    tool_name=tool_name,
                    proposed_params=parameters,
                    task_id=self._current_task_id,
                )

                if approval.action == ApprovalAction.REJECT:
                    return self._build_rejection_result(
                        tool_call, tool_name, parameters, accumulator, approval.reason
                    )

                if (
                    approval.action == ApprovalAction.MODIFY
                    and approval.modified_params
                ):
                    parameters = {**parameters, **approval.modified_params}

            # Execute tool
            tool_result = await self.call_mcp_tool(tool_name, parameters)
            tool_result = self._normalize_tool_result(tool_result)

            accumulator.append(
                ToolCallResultResponse(
                    tool_name=tool_name,
                    parameters=parameters,
                    tool_result=tool_result,
                )
            )

            # Broadcast and return
            await self._broadcast_tool_result(
                query_id, tool_name, parameters, tool_result
            )
            return self._build_tool_message(tool_call.id, tool_result)

        except Exception as e:
            return await self._handle_tool_error(tool_call, accumulator, query_id, e)

    def _normalize_tool_result(self, result: Any) -> Dict[str, Any]:
        """Normalize tool result to dict."""
        if result is None:
            return {"status": "success", "message": "No result returned"}
        if isinstance(result, str):
            if not result.strip():
                return {"status": "success", "message": "Empty response"}
            return json.loads(result)
        return result

    def _build_tool_message(
        self, tool_call_id: str, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build tool result message for LLM context."""
        try:
            content = encode(result)
        except Exception:
            content = json.dumps(result)

        if len(content) > 20000:
            content = content[:20000] + f"... (truncated {len(content) - 20000} chars)"

        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}

    def _build_rejection_result(
        self,
        tool_call: Any,
        tool_name: str,
        parameters: Dict,
        accumulator: List,
        reason: Optional[str],
    ) -> Dict[str, Any]:
        """Build rejection result when user rejects tool."""
        msg = {
            "status": "rejected",
            "reason": reason or "User rejected this action",
            "message": "The user has rejected this action. Please acknowledge and suggest alternatives if applicable.",
        }
        accumulator.append(
            ToolCallResultResponse(
                tool_name=tool_name, parameters=parameters, tool_result=msg
            )
        )
        logger.info(f"{self.agent_type}: Tool '{tool_name}' rejected by user")
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(msg),
        }

    async def _broadcast_tool_result(
        self, query_id: str, tool_name: str, parameters: Dict, result: Dict
    ):
        """Broadcast tool execution to frontend."""
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

    async def _handle_tool_error(
        self, tool_call: Any, accumulator: List, query_id: str, error: Exception
    ) -> Dict[str, Any]:
        """Handle tool execution error."""
        logger.error(f"{self.agent_type}: Tool call failed: {error}")
        error_msg = f"Tool call failed for {tool_call} with {json.loads(getattr(tool_call.function, 'arguments', '{}'))} : {str(error)}"

        accumulator.append(
            ToolCallResultResponse(
                tool_name=getattr(tool_call.function, "name", "unknown"),
                parameters=json.loads(getattr(tool_call.function, "arguments", "{}")),
                tool_result={"error": error_msg},
            )
        )

        await self.publish_broadcast(
            RedisChannels.get_query_updates_channel(query_id),
            MessageType.ERROR,
            {"error": error_msg, "agent_type": self.agent_type},
        )

        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps({"error": error_msg}),
        }

    async def _worker_pull_loop(self):
        queue_key = RedisKeys.get_agent_queue(self.agent_type)
        BLPOP_TIMEOUT = 5  # seconds

        logger.info(
            f"{self.agent_type}[{self.instance_id}]: Starting pull loop from {queue_key}"
        )

        while True:  # Continuous pull loop
            try:
                # BLPOP: Blocking pop from queue (efficient, no polling)
                result = await self.redis.blpop(queue_key, timeout=BLPOP_TIMEOUT)

                if not result:
                    continue  # Timeout, retry

                _, task_data = result
                task_item = TaskQueueItem.model_validate_json(task_data)

                logger.debug(
                    f"{self.agent_type}[{self.instance_id}]: Pulled task from queue: "
                    f"{task_item.sub_query[:50]}... (query_id: {task_item.query_id})"
                )

                # Get SharedData to build CommandMessage
                shared_data = await self._get_shared_data(task_item.query_id)
                if not shared_data:
                    logger.warning(
                        f"{self.agent_type}[{self.instance_id}]: No shared data for "
                        f"{task_item.query_id}, skipping task"
                    )
                    continue

                # Build CommandMessage for processing
                command_message = CommandMessage(
                    agent_type=self.agent_type,
                    command="execute",
                    query_id=task_item.query_id,
                    conversation_id=shared_data.conversation_id,
                    sub_query=task_item.sub_query,
                )

                # Process with distributed lock (handled in handle_command_message)
                await self.handle_command_message(command_message)

            except Exception as e:
                logger.error(
                    f"{self.agent_type}[{self.instance_id}]: Pull loop error: {e}",
                    exc_info=True,
                )
                # Reset state to prevent stale query_id issues
                self._current_query_id = None
                self._current_task_id = None
                await asyncio.sleep(1)

    async def _get_shared_data(self, query_id: str) -> SharedData | None:
        """Fetch SharedData from Redis."""
        try:
            raw = await self.redis.json().get(RedisKeys.get_shared_data_key(query_id))
            return SharedData(**raw) if raw else None
        except Exception as e:
            logger.error(f"Failed to get shared data for {query_id}: {e}")
            return None

    async def listen_channels(self):
        channels = await self.get_sub_channels()

        while True:  # Reconnect loop
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe(*channels)
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue

                    try:
                        command_message = CommandMessage.model_validate_json(
                            message["data"]
                        )
                        if command_message.command == "stop":
                            logger.info(
                                f"{self.agent_type}[{self.instance_id}]: Received stop signal"
                            )
                            await self.stop()
                            return
                        # Add more control commands as needed
                    except Exception as e:
                        logger.debug(f"Ignoring non-command message: {e}")

            except Exception as e:
                logger.error(
                    f"{self.agent_type}[{self.instance_id}]: Signal listener error: {e}"
                )
                await asyncio.sleep(1)
            finally:
                try:
                    await pubsub.unsubscribe(*channels)
                    await pubsub.aclose()
                except Exception:
                    pass

    async def handle_command_message(self, command_message: CommandMessage):
        """Handle incoming command from Manager with distributed lock."""
        if command_message.command != "execute":
            return

        if not command_message.query_id or not command_message.sub_query:
            logger.error(
                f"{self.agent_type}[{self.instance_id}]: Missing query_id or sub_query"
            )
            return

        # Distributed lock to prevent duplicate processing by multiple workers
        lock_key = f"task_lock:{command_message.query_id}:{command_message.sub_query}"
        lock_acquired = await self.redis.set(
            lock_key,
            self.instance_id,
            nx=True,  # Only set if not exists
            ex=310,  # Slightly longer than task timeout
        )

        if not lock_acquired:
            logger.debug(
                f"{self.agent_type}[{self.instance_id}]: Task already claimed by another worker"
            )
            return

        try:
            await self.process_task_with_timeout(command_message)
        finally:
            await self.redis.delete(lock_key)

    async def process_task_with_timeout(self, command_message: CommandMessage):
        """Process task with timeout and proper status management."""
        status_key = RedisKeys.get_agent_instance_status_key(self.agent_type)

        # Set THIS instance to PROCESSING
        await self.redis.hset(
            status_key, self.instance_id, AgentStatus.PROCESSING.value
        )

        try:
            logger.info(
                f"{self.agent_type}[{self.instance_id}]: Processing '{command_message.sub_query[:50]}...' "
                f"for query_id: {command_message.query_id}"
            )

            async with asyncio.timeout(300.0):
                response = await self.process(command_message)
                await self.publish_task_completion(command_message, response)

        except asyncio.TimeoutError:
            logger.error(
                f"{self.agent_type}[{self.instance_id}]: Task timeout after 300s"
            )
        except Exception as e:
            logger.error(f"{self.agent_type}[{self.instance_id}]: Task error: {e}")
        finally:
            # Always reset THIS instance to IDLE
            await self.redis.hset(status_key, self.instance_id, AgentStatus.IDLE.value)

    async def publish_task_completion(
        self, command_message: CommandMessage, response: WorkerAgentProcessResponse
    ):
        """Publish task completion to TASK_UPDATES channel."""
        task_id = await find_task_id(
            self.redis,
            command_message.query_id,
            self.agent_type,
            command_message.sub_query,
        )
        status = TaskStatus.DONE
        error = None

        try:
            await self._store_result_references(
                command_message.query_id, response.tools_result, response.data_resources
            )
        except Exception as e:
            logger.error(f"{self.agent_type}: Failed to store result refs: {e}")
            status = TaskStatus.ERROR
            error = str(e)

        task_update = TaskUpdate(
            task_id=task_id,
            query_id=command_message.query_id,
            sub_query=command_message.sub_query,
            status=status,
            result={
                "tool_results": response.tools_result,
                "resource_results": response.data_resources,
                **(({"error": error}) if error else {}),
            },
            llm_usage=response.llm_usage or {},
            llm_reasoning=response.llm_reasoning,
            agent_type=self.agent_type,
            instance_id=self.instance_id,
        )

        await self.publish_channel(RedisChannels.TASK_UPDATES, task_update, TaskUpdate)

    async def get_mcp_client(self) -> MCPClient:
        if not self.mcp_server_url:
            raise RuntimeError(f"{self.agent_type}: No MCP server configured")

        if not self.mcp_client:
            self.mcp_client = MCPClient(self.mcp_server_url)
            await self.mcp_client.__aenter__()
        return self.mcp_client

    async def call_mcp_tool(
        self, tool_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be non-empty string")
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be dictionary")

        client = await self.get_mcp_client()
        return await client.call_tool(tool_name, parameters)

    async def read_mcp_resource(self, uri: str) -> Dict[str, Any]:
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("uri must be non-empty string")

        client = await self.get_mcp_client()
        return await client.read_resource(uri)

    async def start(self):
        logger.info(
            f"{self.agent_type}[{self.instance_id}]: Starting worker agent (Pull Model)"
        )

        status_key = RedisKeys.get_agent_instance_status_key(self.agent_type)
        await self.redis.hset(status_key, self.instance_id, AgentStatus.IDLE.value)

        await self.init_prompt()

        await asyncio.gather(
            self._worker_pull_loop(),  # Pull tasks from queue
            self.listen_channels(),  # Listen for control signals
        )

    async def init_prompt(self):
        if not self.mcp_server_url:
            logger.warning(f"{self.agent_type}: No MCP server, using fallback prompt")
            self.prompt = (
                f"You are {self.agent_type}: {self.agent_description}\\n\\n"
                "IMPORTANT: MCP tools/resources are unavailable. "
                "Respond with clear limitations and suggest manual alternatives."
            )
            return

        try:
            client = await self.get_mcp_client()

            tools = await client.list_tools()

            tools_dicts = [
                t.model_dump() if hasattr(t, "model_dump") else t for t in tools
            ]
            from src.utils.extract_schema import extract_groq_tools

            self._mcp_tools_for_groq = extract_groq_tools(tools_dicts)

            # HITL: Load tool approval metadata from MCP client
            for tool in tools:
                tool_name = (
                    tool.get("name")
                    if isinstance(tool, dict)
                    else getattr(tool, "name", None)
                )
                if tool_name:
                    hitl = client.get_tool_hitl_metadata(tool_name)
                    if hitl and hitl.requires_approval:
                        self.register_tool_hitl(tool_name, hitl)
                        logger.info(
                            f"{self.agent_type}: Tool '{tool_name}' requires HITL approval "
                            f"(level={hitl.approval_level.value})"
                        )

            self.prompt = build_worker_agent_prompt(
                agent_type=self.agent_type,
                agent_description=self.agent_description,
                examples=self.examples,
            )

            # Đăng ký agent vào registry
            register_agent(
                agent_type=self.agent_type,
                description=self.agent_description,
                tools=tools_dicts,
            )

            logger.info(
                f"{self.agent_type}: Initialized with {len(self._mcp_tools_for_groq)} Groq tools, "
                f"{len(self._tools_hitl_metadata)} require approval"
            )

        except Exception as e:
            logger.error(f"{self.agent_type}: Prompt initialization failed: {e}")
            self.prompt = (
                f"You are {self.agent_type}: {self.agent_description}\\n\\n"
                "IMPORTANT: MCP tools/resources are unavailable. "
                "Respond with clear limitations and suggest manual alternatives."
            )

    async def stop(self):
        logger.info(f"{self.agent_type}[{self.instance_id}]: Stopping worker agent")

        # Cleanup instance registration and status
        try:
            await self.redis.delete(f"worker:{self.agent_type}:{self.instance_id}")
            status_key = RedisKeys.get_agent_instance_status_key(self.agent_type)
            await self.redis.hdel(status_key, self.instance_id)
        except Exception:
            pass

        # Xóa khỏi registry
        unregister_agent(self.agent_type)

        if self.mcp_client:
            try:
                await self.mcp_client.__aexit__(None, None, None)
                logger.info(
                    f"{self.agent_type}[{self.instance_id}]: MCP connection closed"
                )
            except Exception as e:
                logger.error(
                    f"{self.agent_type}[{self.instance_id}]: MCP cleanup error: {e}"
                )
            finally:
                self.mcp_client = None

        if hasattr(super(), "stop"):
            await super().stop()

    async def _store_result_references(
        self,
        query_id: str,
        tool_results: List[ToolCallResultResponse],
        resource_results: List[ResourceCallResponse],
    ) -> None:
        """Store result_id → full result mapping in SharedData for tracing"""
        try:
            shared = await get_shared_data(self.redis, query_id)
            if not shared:
                logger.warning(f"No shared data found for {query_id}")
                return

            for tool_result in tool_results:
                shared.store_result_reference(
                    result_id=tool_result.result_id,
                    tool_name=tool_result.tool_name,
                    tool_result=tool_result.tool_result,
                    agent_type=self.agent_type,
                )

            for resource_result in resource_results:
                shared.store_result_reference(
                    result_id=resource_result.result_id,
                    tool_name=f"resource:{resource_result.resource_name}",
                    tool_result=resource_result.resource_result,
                    agent_type=self.agent_type,
                )

            await update_shared_data(self.redis, query_id, shared)
            logger.debug(
                f"Stored {len(tool_results)} tool + {len(resource_results)} resource references"
            )

        except Exception as e:
            logger.error(f"Error storing result references: {e}", exc_info=True)
