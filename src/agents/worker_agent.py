import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts.worker import build_worker_agent_prompt

from src.mcp.client import BaseMCPClient
from src.typing import BaseAgentResponse, Request
from src.typing.redis import (
    AgentStatus,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskStatus,
    TaskUpdate,
)

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    def __init__(
        self,
        agent_type: str,
        agent_description: str,
        mcp_server_url: Optional[str] = None,
        mcp_timeout: float = 30.0,
        **kwargs,
    ):
        super().__init__(agent_type, **kwargs)
        self.agent_description = agent_description
        self.mcp_server_url = mcp_server_url
        self.mcp_timeout = mcp_timeout
        self.prompt: Optional[str] = None
        self._mcp_client: Optional[BaseMCPClient] = None

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def process(self, request: Request) -> BaseAgentResponse:
        raise NotImplementedError(f"{self.__class__.__name__} must implement process() method")

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)
        
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self._handle_command_message(message["channel"], message["data"])
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_command_message(self, channel: str, raw_data: str):
        if channel != RedisChannels.get_command_channel(self.agent_type):
            logger.warning(f"{self.agent_type}: Ignoring message from wrong channel: {channel}")
            return

        try:
            data = json.loads(raw_data)
            command = data.get("command")
            
            if command != "execute":
                logger.debug(f"{self.agent_type}: Ignoring non-execute command: {command}")
                return

            query_id = data.get("query_id")
            sub_query = data.get("sub_query")

            if not query_id or not sub_query:
                logger.error(f"{self.agent_type}: Missing query_id or sub_query in execute command")
                return

            logger.info(f"{self.agent_type}: Received task execution: '{sub_query}' for {query_id}")
            await self._process_task_with_timeout(query_id, sub_query)

        except json.JSONDecodeError as e:
            logger.error(f"{self.agent_type}: Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"{self.agent_type}: Command message processing failed: {e}")

    async def _process_task_with_timeout(self, query_id: str, sub_query: str):
        await self.redis.hset(RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.PROCESSING.value)

        try:
            logger.info(f"{self.agent_type}: Processing '{sub_query}' for query_id: {query_id}")

            request = Request(query=sub_query, query_id=query_id)
            
            async with asyncio.timeout(300.0):
                response = await self.process(request)

            await self._publish_task_completion_consolidated(query_id, sub_query, response)
            
            await self.redis.hset(RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value)

        except asyncio.TimeoutError:
            logger.error(f"{self.agent_type}: Task processing timeout")
            await self.redis.hset(RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value)
        except Exception as e:
            logger.error(f"{self.agent_type}: Task processing error: {e}")
            await self.redis.hset(RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value)

    async def _publish_task_completion_consolidated(self, query_id: str, sub_query: str, response: BaseAgentResponse):
        try:
            llm_usage_data = {}
            if hasattr(response, "llm_usage") and response.llm_usage:
                if isinstance(response.llm_usage, dict):
                    llm_usage_data = response.llm_usage
                elif hasattr(response.llm_usage, "model_dump"):
                    llm_usage_data = response.llm_usage.model_dump()
                else:
                    llm_usage_data = {
                        attr: getattr(response.llm_usage, attr, None)
                        for attr in ["completion_tokens", "prompt_tokens", "total_tokens", 
                                   "completion_time", "prompt_time", "queue_time", "total_time"]
                    }

            result_data = response.result or ""
            if isinstance(result_data, str) and result_data.strip().startswith(("{", "[")):
                try:
                    result_data = json.loads(result_data)
                except json.JSONDecodeError:
                    pass

            task_id = await self._resolve_task_id_inline(query_id, sub_query)

            completion_message = {
                "query_id": query_id,
                "sub_query": sub_query,
                "task_id": task_id,
                "status": TaskStatus.DONE,
                "results": {sub_query: result_data},
                "context": {sub_query: response.context or {}},
                "llm_usage": llm_usage_data,
                "timestamp": datetime.now().isoformat(),
                "agent_type": self.agent_type,
            }

            await self.publish_channel(RedisChannels.TASK_UPDATES, completion_message)
            logger.info(f"{self.agent_type}: Task completion published for {query_id}")

        except Exception as e:
            logger.error(f"{self.agent_type}: Task completion publishing failed: {e}")
            raise

    async def _resolve_task_id_inline(self, query_id: str, sub_query: str) -> Optional[str]:
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data_raw = await self.redis.json().get(shared_key)

            if shared_data_raw:
                shared_data = SharedData(**shared_data_raw)
                if self.agent_type in shared_data.task_graph.nodes:
                    for task in shared_data.task_graph.nodes[self.agent_type]:
                        if task.sub_query == sub_query:
                            return task.task_id
            return None
        except Exception as e:
            logger.error(f"Task ID resolution failed: {e}")
            return None

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in await self.get_pub_channels():
            raise ValueError(f"WorkerAgent cannot publish to {channel}")

        try:
            validated = TaskUpdate(**message) if channel == RedisChannels.TASK_UPDATES else message
            message_json = validated.model_dump_json() if hasattr(validated, 'model_dump_json') else json.dumps(validated)
            await self.redis.publish(channel=channel, message=message_json)
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def _get_mcp_client(self) -> BaseMCPClient:
        if not self.mcp_server_url:
            raise RuntimeError(f"{self.agent_type}: No MCP server configured")

        if not self._mcp_client:
            self._mcp_client = BaseMCPClient(self.mcp_server_url, self.mcp_timeout)
            await self._mcp_client.__aenter__()
        return self._mcp_client

    async def call_mcp_tool(self, tool_name: str, params: Dict[str, Any]) -> Optional[str]:
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be non-empty string")
        if not isinstance(params, dict):
            raise ValueError("params must be dictionary")

        client = await self._get_mcp_client()
        return await client.call_tool(tool_name, params)

    async def read_mcp_resource(self, uri: str) -> Optional[str]:
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("uri must be non-empty string")

        client = await self._get_mcp_client()
        return await client.read_resource(uri)

    async def start(self):
        logger.info(f"{self.agent_type}: Starting worker agent")

        await self.redis.hset(RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value)

        await self._initialize_prompt_consolidated()

        await self.listen_channels()

    async def _initialize_prompt_consolidated(self):
        if not self.mcp_server_url:
            logger.warning(f"{self.agent_type}: No MCP server, using fallback prompt")
            self.prompt = (
                f"You are {self.agent_type}: {self.agent_description}\\n\\n"
                "IMPORTANT: MCP tools/resources are unavailable. "
                "Respond with clear limitations and suggest manual alternatives."
            )
            return

        try:
            client = await self._get_mcp_client()

            tools = await client.list_tools()
            resources = []
            try:
                resources = await client.list_resource_templates()
            except Exception as e:
                logger.debug(f"{self.agent_type}: Resource templates unavailable: {e}")

            self.prompt = build_worker_agent_prompt(
                agent_type=self.agent_type,
                agent_description=self.agent_description,
                tools=tools,
                resources=resources,
                tools_example="",
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

        if self._mcp_client:
            try:
                await self._mcp_client.__aexit__(None, None, None)
                logger.info(f"{self.agent_type}: MCP connection closed")
            except Exception as e:
                logger.error(f"{self.agent_type}: MCP cleanup error: {e}")
            finally:
                self._mcp_client = None

        if hasattr(super(), "stop"):
            await super().stop()