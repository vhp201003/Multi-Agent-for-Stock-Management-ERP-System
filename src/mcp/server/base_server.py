"""Base MCP Server for WorkerAgents. Provides infrastructure to expose tools/resources."""

import logging
from abc import ABC, abstractmethod

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


class BaseMCPServer(ABC):
    """Base class for agent MCP servers. Subclasses define tools/resources.

    This class provides common infrastructure for all agent MCP servers,
    including initialization, registration hooks, and server lifecycle management.

    Attributes:
        name (str): Name of the MCP server (e.g., "InventoryMCP").
        host (str): Host address for the server.
        port (int): Port number for the server.
        mcp (FastMCP): FastMCP instance for handling MCP protocol.

    Example:
        class MyAgentMCPServer(BaseMCPServer):
            def _register_tools(self):
                @self.mcp.tool(name="my_tool", description="...")
                async def my_tool(param: str) -> str:
                    return "result"
    """

    def __init__(
        self, name: str, host: str = "127.0.0.1", port: int = 8000, debug: bool = False
    ):
        """Initialize MCP server with name, host, and port.

        Args:
            name (str): Name of the MCP server (e.g., "InventoryMCP").
            host (str): Host address. Defaults to "127.0.0.1".
            port (int): Port number. Defaults to 8000.
            debug (bool): Enable debug logging. Defaults to False.
        """
        self.name = name
        self.host = host
        self.port = port
        self.mcp = FastMCP(
            name=name,
            stateless_http=True,
            host=host,
            port=port,
            debug=debug,
        )
        self._register_tools()
        self._register_resources()
        logger.info(f"Initialized {name} MCP Server on {host}:{port}")

    @abstractmethod
    def _register_tools(self):
        """Register tools for this agent. Must be implemented by subclasses.

        Subclasses should use @self.mcp.tool() decorator to register tools.
        Tools should have Pydantic models for parameters and return types.
        """
        pass

    @abstractmethod
    def _register_resources(self):
        """Register resources for this agent. Must be implemented by subclasses.

        Subclasses should use @self.mcp.resource() decorator to register resources.
        Resources should return structured data (JSON) or text.
        """
        pass

    def run(self):
        """Start the MCP server.

        Blocks until server is stopped. Should be run in a separate thread/task.
        """
        logger.info(f"Starting {self.name} MCP Server on {self.host}:{self.port}...")
        self.mcp.run(transport="streamable-http")
