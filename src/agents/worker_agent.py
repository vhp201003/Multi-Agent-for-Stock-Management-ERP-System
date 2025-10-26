import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.worker import build_worker_agent_prompt

from src.mcp.client import MCPClient
from src.typing import (
    ResourceCallResponse,
    ToolCallResponse,
    ToolCallResultResponse,
    ToolCallSchema,
    WorkerAgentProcessResponse,
)
from src.typing.redis import (
    AgentStatus,
    CommandMessage,
    ConversationData,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.schema.tool_call import ToolCallPlan

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    def __init__(
        self,
        agent_type: str,
        agent_description: str,
        mcp_server_url: Optional[str] = None,
        mcp_timeout: float = 30.0,
        examples: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(agent_type, **kwargs)
        self.agent_description = agent_description
        self.mcp_server_url = mcp_server_url
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
        conversation_key = RedisKeys.get_conversation_key(
            command_message.conversation_id
        )
        conversation_data = await self.redis.json().get(conversation_key)
        if conversation_data is None:
            logger.error(
                f"No conversation data found for {command_message.conversation_id}"
            )
            # Create a minimal conversation for processing
            conversation = ConversationData(
                conversation_id=command_message.conversation_id,
                messages=[],
                summary=None,
            )
        else:
            conversation = ConversationData(**conversation_data)
        # Summary conversation context
        summary = conversation.summary
        messages = [
            {
                "role": "system",
                "content": self.prompt,
            },
            {
                "role": "assistant",
                "content": f"Conversation Summary: {summary}",
            },
            {
                "role": "user",
                "content": sub_query,
            },
        ]

        ### Phase 2: Call LLM to get tool and resource usage
        llm_response: ToolCallResponse = await self._call_llm(
            query_id=command_message.query_id,
            conversation_id=command_message.conversation_id,
            messages=messages,
            response_schema=ToolCallSchema,
            response_model=ToolCallResponse,
        )

        ### Phase 3: execute tool calls and resource reads
        ### 3.1 Extract tool calls and execute tools

        worker_process_result = WorkerAgentProcessResponse()
        worker_process_result.query_id = command_message.query_id
        worker_process_result.conversation_id = command_message.conversation_id
        worker_process_result.result = llm_response.result
        worker_process_result.llm_reasoning = llm_response.llm_reasoning

        mixed_calls = llm_response.result.tool_calls or []
        tool_calls = [item for item in mixed_calls if isinstance(item, ToolCallPlan)]
        read_resources = [item for item in mixed_calls if isinstance(item, str)]

        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.tool_name
                parameters = tool_call.parameters
                try:
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
                except Exception as e:
                    worker_process_result.tools_result.append(
                        ToolCallResultResponse(
                            tool_name=tool_name,
                            parameters=parameters,
                            tool_result={"error": f"Tool call failed: {str(e)}"},
                        )
                    )

        ### 3.1 Extract resource reads and read resources
        if read_resources:
            for resource in read_resources:
                try:
                    resource_result = await self.read_mcp_resource(resource)
                    worker_process_result.data_resources.append(
                        ResourceCallResponse(
                            resource_name=resource, resource_result=resource_result
                        )
                    )
                except Exception as e:
                    worker_process_result.data_resources.append(
                        ResourceCallResponse(
                            resource_name=resource,
                            resource_result={
                                "error": f"Resource read failed: {str(e)}"
                            },
                        )
                    )

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
            resources = await client.list_resource_templates()

            self.prompt = build_worker_agent_prompt(
                agent_type=self.agent_type,
                agent_description=self.agent_description,
                tools=tools,
                resources=resources,
                examples=self.examples,
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
