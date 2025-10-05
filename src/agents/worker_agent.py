import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts.worker import build_worker_agent_prompt

from src.mcp.client import BaseMCPClient
from src.typing import BaseAgentResponse, Request
from src.typing.redis import AgentStatus, CommandMessage, TaskUpdate
from src.typing.redis.constants import RedisChannels, RedisKeys, TaskStatus

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    """Base worker agent with MCP integration and task processing."""

    def __init__(
        self,
        name: str,
        agent_description: str,
        mcp_server_url: Optional[str] = None,
        mcp_timeout: float = 30.0,
        **kwargs,
    ):
        super().__init__(name, **kwargs)
        self.agent_description = agent_description
        self.mcp_server_url = mcp_server_url
        self.mcp_timeout = mcp_timeout
        self.prompt: Optional[str] = None
        self._mcp_client: Optional[BaseMCPClient] = None

    async def get_pub_channels(self) -> List[str]:
        """Channels for publishing task completion updates."""
        return [RedisChannels.get_task_updates_channel(self.name)]

    async def get_sub_channels(self) -> List[str]:
        """Channels for receiving task execution commands."""
        return [RedisChannels.get_command_channel(self.name)]

    async def update_shared_data_from_message(
        self, channel: str, message: Dict[str, Any]
    ):
        """Process task execution commands directly from Manager."""
        # Security: Validate channel source
        if channel != RedisChannels.get_command_channel(self.name):
            logger.warning(
                f"{self.name}: Ignoring message from wrong channel: {channel}"
            )
            return

        try:
            # Validate command structure
            command = message.get("command")
            if command != "execute":
                logger.debug(f"{self.name}: Ignoring non-execute command: {command}")
                return

            query_id = message.get("query_id")
            sub_query = message.get("sub_query")

            if not query_id:
                logger.error(f"{self.name}: Missing query_id in execute command")
                return

            if not sub_query:
                logger.error(f"{self.name}: Missing sub_query in execute command")
                return

            logger.info(
                f"{self.name}: Received task execution: '{sub_query}' for {query_id}"
            )

            # Process task directly with provided data
            await self._process_task_direct(query_id, sub_query)

        except Exception as e:
            logger.exception(f"{self.name}: Command message processing failed: {e}")

    async def listen_channels(self):
        """Listen to command channels and process task execution."""
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)
        logger.info(f"{self.name} listening on {channels}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        channel = message["channel"]

                        # Parse message for worker channels
                        parsed_message = await self._parse_channel_message(
                            channel, data
                        )

                        # Dispatch to shared data update handler
                        await self.update_shared_data_from_message(
                            channel=channel,
                            message=parsed_message.model_dump()
                            if hasattr(parsed_message, "model_dump")
                            else parsed_message,
                        )
                    except Exception as e:
                        logger.error(f"{self.name} message processing error: {e}")

        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        """Publish task completion updates."""
        # Validate channel
        if channel not in await self.get_pub_channels():
            raise ValueError(f"WorkerAgent cannot publish to {channel}")

        # Determine model based on channel
        model = (
            TaskUpdate
            if channel == RedisChannels.get_task_updates_channel(self.name)
            else None
        )

        try:
            if model:
                validated = model(**message)
                await self.redis.publish(
                    channel=channel, message=validated.model_dump_json()
                )
            else:
                await self.redis.publish(channel=channel, message=json.dumps(message))
            logger.info(f"{self.name} published on {channel}: {message}")
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def _parse_channel_message(self, channel: str, data: Dict[str, Any]) -> Any:
        """Parse messages for worker-specific channels."""
        try:
            if channel == RedisChannels.get_command_channel(self.name):
                # Worker receives execution commands
                return CommandMessage(**data)
            else:
                logger.warning(f"WorkerAgent: Unknown channel: {channel}")
                return data
        except Exception as e:
            logger.error(f"WorkerAgent: Message parsing failed for {channel}: {e}")
            raise ValueError(
                f"Invalid message format for worker channel {channel}: {e}"
            )

    async def _get_mcp_client(self) -> BaseMCPClient:
        """Get persistent MCP client with lazy initialization."""
        if not self.mcp_server_url:
            raise RuntimeError(f"{self.name}: No MCP server configured")

        if not self._mcp_client:
            self._mcp_client = BaseMCPClient(self.mcp_server_url, self.mcp_timeout)
            await self._mcp_client.__aenter__()
            logger.info(f"{self.name}: Connected to MCP server")

        return self._mcp_client

    async def initialize_prompt(self):
        """Initialize system prompt from MCP server with graceful fallback."""
        if not self.mcp_server_url:
            logger.warning(f"{self.name}: No MCP server, using fallback prompt")
            self._set_fallback_prompt()
            return

        try:
            client = await self._get_mcp_client()

            # Gather MCP capabilities
            tools = await client.list_tools()
            resources = await self._safe_get_resources(client)

            # Build enhanced prompt
            self.prompt = build_worker_agent_prompt(
                agent_name=self.name,
                agent_description=self.agent_description,
                tools=tools,
                resources=resources,
            )

            logger.info(
                f"{self.name}: Initialized with {len(tools)} tools, {len(resources)} resources"
            )

        except Exception as e:
            logger.error(f"{self.name}: Prompt initialization failed: {e}")
            self._set_fallback_prompt()

    def _set_fallback_prompt(self):
        """Set secure fallback prompt when MCP unavailable."""
        self.prompt = (
            f"You are {self.name}: {self.agent_description}\n\n"
            "IMPORTANT: MCP tools/resources are unavailable. "
            "Respond with clear limitations and suggest manual alternatives."
        )

    async def _safe_get_resources(self, client: BaseMCPClient) -> List[Dict[str, Any]]:
        """Safely retrieve MCP resources with error handling."""
        try:
            return await client.list_resource_templates()
        except Exception as e:
            logger.debug(f"{self.name}: Resource templates unavailable: {e}")
            return []

    async def call_mcp_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> Optional[str]:
        """Execute MCP tool call with validation."""
        # Input validation (Security)
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be non-empty string")
        if not isinstance(params, dict):
            raise ValueError("params must be dictionary")

        client = await self._get_mcp_client()
        return await client.call_tool(tool_name, params)

    async def read_mcp_resource(self, uri: str) -> Optional[str]:
        """Read MCP resource with validation."""
        if not isinstance(uri, str) or not uri.strip():
            raise ValueError("uri must be non-empty string")

        client = await self._get_mcp_client()
        return await client.read_resource(uri)

    async def _process_task_direct(self, query_id: str, sub_query: str):
        """Process task with data received directly from Manager command."""
        await self._update_status(AgentStatus.PROCESSING)

        try:
            logger.info(
                f"{self.name}: Processing '{sub_query}' for query_id: {query_id}"
            )

            # Execute business logic with timeout
            request = Request(query=sub_query, query_id=query_id)
            async with asyncio.timeout(300.0):  # 5 min processing timeout
                response = await self.process(request)

            # Publish completion (Manager will handle shared data updates)
            await self._publish_task_completion(query_id, sub_query, response)
            await self._update_status(AgentStatus.IDLE)

        except asyncio.TimeoutError:
            logger.error(f"{self.name}: Task processing timeout")
            await self._update_status(AgentStatus.ERROR)
        except Exception as e:
            logger.exception(f"{self.name}: Task processing error: {e}")
            await self._update_status(AgentStatus.ERROR)

    async def _publish_task_completion(
        self, query_id: str, sub_query: str, response: BaseAgentResponse
    ):
        """Broadcast task completion to Manager for processing."""
        try:
            # Publish completion event (Manager will handle shared data updates)
            completion_message = {
                "query_id": query_id,
                "sub_query": sub_query,
                "status": TaskStatus.DONE,
                "results": {sub_query: response.result or ""},
                "context": {sub_query: response.context or {}},
                "llm_usage": response.llm_usage or {},
                "timestamp": datetime.now().isoformat(),
                "update_type": "task_completed",
            }

            await self.publish_channel(
                RedisChannels.get_task_updates_channel(self.name), completion_message
            )
            logger.info(f"{self.name}: Broadcasted completion for query_id: {query_id}")

        except Exception as e:
            logger.error(f"{self.name}: Task completion broadcasting failed: {e}")
            raise

    async def _update_status(self, status: AgentStatus):
        """Update agent status in Redis with error handling."""
        try:
            await self.redis.hset(RedisKeys.AGENT_STATUS, self.name, status.value)
            logger.debug(f"{self.name}: Status updated to {status.value}")
        except Exception as e:
            logger.error(f"{self.name}: Status update failed: {e}")

    async def process(self, request: Request) -> BaseAgentResponse:
        """Process business request - MUST be implemented by subclasses."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement process() method"
        )

    async def start(self):
        """Start worker agent with full initialization."""
        logger.info(f"{self.name}: Starting worker agent")

        # Initialize capabilities
        await self.initialize_prompt()
        await self._update_status(AgentStatus.IDLE)

        # Start listening for commands
        await self.listen_channels()

    async def stop(self):
        """Stop worker agent and cleanup resources."""
        logger.info(f"{self.name}: Stopping worker agent")

        # Cleanup MCP connection
        if self._mcp_client:
            try:
                await self._mcp_client.__aexit__(None, None, None)
                logger.info(f"{self.name}: MCP connection closed")
            except Exception as e:
                logger.warning(f"{self.name}: MCP cleanup error: {e}")
            finally:
                self._mcp_client = None

        # Call parent cleanup
        if hasattr(super(), "stop"):
            await super().stop()
