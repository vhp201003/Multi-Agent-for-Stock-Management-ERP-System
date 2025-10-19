import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(self, server_url: str, timeout: float = 30.0):
        parsed = urlparse(server_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid MCP server URL: {server_url}")

        self.server_url = server_url
        self.timeout = timeout
        self._session: Optional[ClientSession] = None
        self._exit_stack = None

    def _ensure_connected(self):
        if not self._session:
            raise RuntimeError("Client not connected. Use 'async with' pattern.")

    async def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        async with asyncio.timeout(self.timeout):
            result = await self._session.list_tools()
            return [tool.model_dump() for tool in result.tools]

    async def call_tool(
        self, tool_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not tool_name or not tool_name.strip():
            raise ValueError("tool_name must be non-empty string")
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be dictionary")

        self._ensure_connected()
        async with asyncio.timeout(self.timeout):
            result = await self._session.call_tool(tool_name, parameters)
            return result.content[0].text if result.content else None

    async def list_resource_templates(self) -> List[Dict[str, Any]]:
        self._ensure_connected()
        async with asyncio.timeout(self.timeout):
            result = await self._session.list_resource_templates()
            return [tpl.model_dump() for tpl in result.resourceTemplates]

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        if not uri or not uri.strip():
            raise ValueError("uri must be non-empty string")

        self._ensure_connected()
        async with asyncio.timeout(self.timeout):
            result = await self._session.read_resource(uri)
            return result.contents[0].text if result.contents else None

    async def __aenter__(self):
        try:
            async with asyncio.timeout(self.timeout):
                self._exit_stack = streamablehttp_client(self.server_url)
                read, write, _ = await self._exit_stack.__aenter__()

                self._session = ClientSession(read, write)
                await self._session.__aenter__()
                await self._session.initialize()

            logger.info(f"Connected to {self.server_url}")
            return self
        except Exception as e:
            await self._cleanup()
            raise RuntimeError(f"Connection failed: {e}")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._cleanup()
        return False

    async def _cleanup(self):
        for resource in [self._session, self._exit_stack]:
            if resource:
                try:
                    await resource.__aexit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Cleanup error: {e}")

        self._session = None
        self._exit_stack = None
