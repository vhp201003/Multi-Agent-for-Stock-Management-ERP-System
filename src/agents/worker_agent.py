import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.worker import build_worker_agent_prompt
from config.settings import get_agent_config
from src.mcp.client import MCPClient
from src.typing import (
    ResourceCallResponse,
    ToolCallResponse,
    ToolCallResultResponse,
    WorkerAgentProcessResponse,
)
from src.typing.redis import (
    AgentStatus,
    CommandMessage,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.utils.converstation import get_summary_conversation
from src.utils.shared_data_utils import get_shared_data, update_shared_data

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    def __init__(
        self,
        agent_type: str,
        agent_description: str,
        mcp_timeout: float = 30.0,
        examples: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(agent_type, **kwargs)
        self.agent_description = agent_description
        self.mcp_server_url = get_agent_config(agent_type).mcp_server_url
        self.mcp_timeout = mcp_timeout
        self.prompt: Optional[str] = None
        self.mcp_client: Optional[MCPClient] = None
        self.examples = examples

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def process(
        self, command_message: CommandMessage
    ) -> WorkerAgentProcessResponse:
        ### Phase 1: Load conversation and prepare messages
        sub_query = command_message.sub_query
        conversation_id = command_message.conversation_id

        # Get conversation summary
        summary = await get_summary_conversation(self.redis, conversation_id)

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
            {
                "role": "user",
                "content": sub_query,
            },
        ]

        ### Phase 2: Call LLM to get tool calls from Groq tool_calls
        groq_tools = None
        if hasattr(self, "_mcp_tools_for_groq"):
            groq_tools = self._mcp_tools_for_groq

        # Call LLM with tools but WITHOUT response_schema
        # Groq will return tool_calls in message.tool_calls
        llm_response: ToolCallResponse = await self._call_llm(
            query_id=command_message.query_id,
            conversation_id=command_message.conversation_id,
            messages=messages,
            response_model=ToolCallResponse,
            tools=groq_tools,
        )

        ### Phase 3: Extract tool calls from Groq and execute them
        worker_process_result = WorkerAgentProcessResponse()
        worker_process_result.query_id = command_message.query_id
        worker_process_result.conversation_id = command_message.conversation_id
        worker_process_result.llm_reasoning = llm_response.llm_reasoning

        # Extract tool_calls from Groq response
        groq_tool_calls = []
        if (
            isinstance(llm_response.result, dict)
            and "tool_calls" in llm_response.result
        ):
            groq_tool_calls = llm_response.result.get("tool_calls", [])

        if groq_tool_calls:
            for groq_tool_call in groq_tool_calls:
                # groq_tool_call is ChatCompletionMessageToolCall
                # Extract tool_name and parameters from groq_tool_call.function
                try:
                    tool_name = groq_tool_call.function.name
                    # Parameters come as JSON string, need to parse
                    parameters_json = groq_tool_call.function.arguments
                    if isinstance(parameters_json, str):
                        parameters = json.loads(parameters_json)
                    else:
                        parameters = parameters_json

                    tool_result: Dict[str, Any] = await self.call_mcp_tool(
                        tool_name, parameters
                    )
                    # Parse JSON string to dict if needed
                    if isinstance(tool_result, str):
                        tool_result = json.loads(tool_result)

                    worker_process_result.tools_result.append(
                        ToolCallResultResponse(
                            tool_name=tool_name,
                            parameters=parameters,
                            tool_result=tool_result,
                        )
                    )
                    logger.debug(
                        f"{self.agent_type}: Executed tool '{tool_name}' with result"
                    )
                except Exception as e:
                    logger.error(
                        f"{self.agent_type}: Tool call failed for {groq_tool_call}: {e}"
                    )
                    worker_process_result.tools_result.append(
                        ToolCallResultResponse(
                            tool_name=getattr(
                                groq_tool_call.function, "name", "unknown"
                            ),
                            parameters=json.loads(
                                getattr(groq_tool_call.function, "arguments", "{}")
                            ),
                            tool_result={"error": f"Tool call failed: {str(e)}"},
                        )
                    )
        else:
            logger.debug(f"{self.agent_type}: No tool calls requested by LLM")

        return worker_process_result

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    command_message = CommandMessage.model_validate_json(
                        message["data"]
                    )
                    await self.handle_command_message(command_message)
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def handle_command_message(self, command_message: CommandMessage):
        try:
            if command_message.command != "execute":
                logger.debug(
                    f"{self.agent_type}: Ignoring non-execute command: {command_message.command}"
                )
                return

            query_id = command_message.query_id
            sub_query = command_message.sub_query

            if not query_id or not sub_query:
                logger.error(
                    f"{self.agent_type}: Missing query_id or sub_query in execute command"
                )
                return

            await self.process_task_with_timeout(command_message)

        except Exception as e:
            logger.error(f"{self.agent_type}: Command message processing failed: {e}")

    async def process_task_with_timeout(self, command_message: CommandMessage):
        # Mark agent as processing
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.PROCESSING.value
        )

        try:
            logger.info(
                f"{self.agent_type}: Processing '{command_message.sub_query}' for query_id: {command_message.query_id}"
            )

            async with asyncio.timeout(300.0):
                response: WorkerAgentProcessResponse = await self.process(
                    command_message
                )

                await self.publish_task_completion(command_message, response)

                # Mark agent as idle before publishing, so manager can execute next task
                await self.redis.hset(
                    RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value
                )
        except asyncio.TimeoutError:
            logger.error(f"{self.agent_type}: Task processing timeout")
            await self.redis.hset(
                RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value
            )
        except Exception as e:
            logger.error(f"{self.agent_type}: Task processing error: {e}")
            await self.redis.hset(
                RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value
            )

    async def publish_task_completion(
        self, command_message: CommandMessage, response: WorkerAgentProcessResponse
    ):
        try:
            task_id = await self.find_task_id_by_query(
                command_message.query_id, command_message.sub_query
            )

            await self._store_result_references(
                command_message.query_id, response.tools_result, response.data_resources
            )

            task_update: TaskUpdate = TaskUpdate(
                task_id=task_id,
                query_id=command_message.query_id,
                sub_query=command_message.sub_query,
                status=TaskStatus.DONE,
                result={
                    "tool_results": response.tools_result,
                    "resource_results": response.data_resources,
                },
                llm_usage=response.llm_usage or {},
                llm_reasoning=response.llm_reasoning,
                agent_type=self.agent_type,
            )

        except Exception as e:
            logger.error(f"{self.agent_type}: Task completion publishing failed: {e}")
            task_update: TaskUpdate = TaskUpdate(
                task_id=task_id,
                query_id=command_message.query_id,
                sub_query=command_message.sub_query,
                status=TaskStatus.ERROR,
                result={
                    "tool_results": response.tools_result,
                    "resource_results": response.data_resources,
                    "error": str(e),
                },
                llm_usage=response.llm_usage or {},
                llm_reasoning=response.llm_reasoning,
                agent_type=self.agent_type,
            )
            raise
        finally:
            await self.publish_channel(
                RedisChannels.TASK_UPDATES, task_update, TaskUpdate
            )
            # Also publish to the query-specific updates channel
            await self.publish_channel(
                RedisChannels.get_query_updates_channel(command_message.query_id),
                task_update,
                TaskUpdate,
            )

    async def find_task_id_by_query(
        self, query_id: str, sub_query: str
    ) -> Optional[str]:
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data_raw = await self.redis.json().get(shared_key)

            if shared_data_raw:
                shared_data = SharedData(**shared_data_raw)
                return shared_data.get_task_id_by_sub_query(self.agent_type, sub_query)
            return None
        except Exception as e:
            logger.error(f"Task ID resolution failed: {e}")
            return None

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
        logger.info(f"{self.agent_type}: Starting worker agent")

        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value
        )

        await self.init_prompt()

        await self.listen_channels()

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

            self.prompt = build_worker_agent_prompt(
                agent_type=self.agent_type,
                agent_description=self.agent_description,
                examples=self.examples,
            )

            logger.info(
                f"{self.agent_type}: Initialized with {len(self._mcp_tools_for_groq)} Groq tools"
            )

        except Exception as e:
            logger.error(f"{self.agent_type}: Prompt initialization failed: {e}")
            self.prompt = (
                f"You are {self.agent_type}: {self.agent_description}\\n\\n"
                "IMPORTANT: MCP tools/resources are unavailable. "
                "Respond with clear limitations and suggest manual alternatives."
            )

    async def stop(self):
        logger.info(f"{self.agent_type}: Stopping worker agent")

        if self.mcp_client:
            try:
                await self.mcp_client.__aexit__(None, None, None)
                logger.info(f"{self.agent_type}: MCP connection closed")
            except Exception as e:
                logger.error(f"{self.agent_type}: MCP cleanup error: {e}")
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
