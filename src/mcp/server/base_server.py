import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.typing.mcp.base import HITLMetadata

logger = logging.getLogger(__name__)


@dataclass
class ServerMetrics:
    request_count: int = 0
    error_count: int = 0
    start_time: float = 0

    @property
    def success_rate(self) -> float:
        if self.request_count == 0:
            return 100.0
        return ((self.request_count - self.error_count) / self.request_count) * 100


class ServerConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="Server name")
    host: str = Field(default="127.0.0.1", description="Host address")
    port: int = Field(default=8000, ge=1024, le=65535, description="Port number")
    debug: bool = Field(default=False, description="Debug mode")
    shutdown_timeout: float = Field(
        default=30.0, description="Shutdown timeout seconds"
    )


class BaseMCPServer(ABC):
    """
    Base MCP Server leveraging FastMCP for simplified implementation.

    This class wraps FastMCP and provides a clean API for registering tools and resources.
    It automatically handles Pydantic model serialization for tool parameters and resources.

    Usage:
        class InventoryMCPServer(BaseMCPServer):
            def setup(self):
                # Register tools with Pydantic models - parameters are auto-validated
                self.add_tool(self.check_stock)
                self.add_tool(self.list_items)

                # Register resources with URI templates
                self.add_resource("stock://{product_id}", self.get_stock_level)
                self.add_resource("alerts://all", self.get_alerts)

            # Tools can use Pydantic models for parameters
            async def check_stock(
                self,
                product_id: str = Field(..., description="Product ID"),
                warehouse: str = Field(default="MAIN", description="Warehouse code")
            ) -> dict:
                return {"stock": 100, "product_id": product_id, "warehouse": warehouse}

            # Resources with parameters
            async def get_stock_level(self, product_id: str) -> str:
                return f"Stock level for {product_id}: 150 units"

            async def list_items(self) -> dict:
                return {"items": ["item1", "item2"], "count": 2}

            async def get_alerts(self) -> str:
                return "2 critical alerts, 5 warnings"

        # Run server
        config = ServerConfig(name="InventoryServer", port=8002)
        server = InventoryMCPServer(config)
        server.run()
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.server_id = str(uuid.uuid4())
        self.metrics = ServerMetrics()
        self._shutdown_event = asyncio.Event()
        self._is_running = False
        self.logger = self._setup_logger()

        # Initialize FastMCP with configuration
        self.mcp = FastMCP(
            name=config.name,
            host=config.host,
            port=config.port,
            debug=config.debug,
            stateless_http=True,
        )

    def _setup_logger(self) -> logging.Logger:
        server_logger = logging.getLogger(f"{self.config.name}-{self.server_id}")

        if not server_logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s - server_id=%(server_id)s",
                defaults={"server_id": self.server_id},
            )

            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            server_logger.addHandler(handler)
            server_logger.setLevel(logging.DEBUG if self.config.debug else logging.INFO)

        return server_logger

    def _get_metrics_data(self) -> dict:
        return {
            "server_id": self.server_id,
            "metrics": {
                "request_count": self.metrics.request_count,
                "error_count": self.metrics.error_count,
                "success_rate": round(self.metrics.success_rate, 2),
                "uptime_seconds": round(time.time() - self.metrics.start_time, 2),
            },
        }

    def _setup_metrics_endpoint(self) -> None:
        """Register metrics endpoint with FastMCP."""

        @self.mcp.custom_route("/metrics", methods=["GET"])
        async def metrics_endpoint(request):
            return self._get_metrics_data()

    # ============= Public API for Subclasses =============

    def add_tool(
        self,
        fn,
        name: str | None = None,
        description: str | None = None,
        structured_output: bool | None = None,
        hitl: Optional[HITLMetadata] = None,
    ) -> None:
        """
        Register a tool function with FastMCP.

        FastMCP automatically extracts parameter information from function signature,
        including Pydantic Field descriptions. Works with both sync and async functions.

        Args:
            fn: Function to register as a tool
            name: Optional tool name (defaults to function name)
            description: Optional tool description
            structured_output: Controls output schema generation
                - None: Auto-detect from return type annotation (default)
                - True: Force structured output (requires Pydantic return type)
                - False: Force unstructured output (dict/str)
            hitl: Optional Human-in-the-Loop metadata for approval workflow
                - If provided, tool will require user approval before execution
                - Agent reads this from tool annotations at runtime

        Example - Tool with HITL:
            self.add_tool(
                self.create_purchase_order,
                description="Create a new purchase order",
                hitl=HITLMetadata(
                    requires_approval=True,
                    approval_level=ApprovalLevel.REVIEW,
                    modifiable_fields=["quantity", "supplier_id"],
                    approval_message="Please review this purchase order"
                )
            )
        """
        # Build annotations with HITL metadata as extra fields
        annotations: Optional[ToolAnnotations] = None
        if hitl:
            # Note: Can't store on bound method, so just log and use annotations
            # Convert HITLMetadata to x-hitl-* fields in ToolAnnotations
            annotations = ToolAnnotations(**hitl.to_annotations())
            self.logger.info(
                f"Tool '{name or fn.__name__}' registered with HITL: "
                f"level={hitl.approval_level.value}, modifiable={hitl.modifiable_fields}"
            )

        self.mcp.add_tool(
            fn,
            name=name,
            description=description,
            annotations=annotations,
            structured_output=structured_output,
        )

    def get_tool_hitl_metadata(self, tool_name: str) -> Optional[HITLMetadata]:
        """
        Get HITL metadata for a registered tool.

        Used internally to check if a tool requires approval.
        """
        # Look up the tool in FastMCP's registry
        tool_manager = getattr(self.mcp, "_tool_manager", None)
        if tool_manager and hasattr(tool_manager, "tools"):
            tool = tool_manager.tools.get(tool_name)
            if tool and hasattr(tool, "fn"):
                return getattr(tool.fn, "_hitl_metadata", None)
        return None

    def add_resource(self, uri_template: str, fn) -> None:
        """
        Register a resource with FastMCP.

        FastMCP automatically handles URI template parameters. The function can be
        async or sync, and can return str, bytes, or dict (will be JSON-encoded).

        Args:
            uri_template: URI pattern (e.g., "stock://{product_id}" or "alerts://all")
            fn: Function to handle resource reads

        Example:
            async def get_stock_level(product_id: str) -> str:
                return f"Stock for {product_id}: 100 units"

            self.add_resource("stock://{product_id}", get_stock_level)
        """
        self.mcp.resource(uri_template)(fn)

    def add_prompt(self, name: str, fn) -> None:
        """
        Register a prompt with FastMCP.

        Prompts are parameterizable message templates useful for guiding LLM behavior.

        Args:
            name: Prompt name
            fn: Async function returning list of prompt messages

        Example:
            async def analyze_data(data_type: str) -> list[dict]:
                return [{
                    "role": "user",
                    "content": f"Analyze this {data_type} data"
                }]

            self.add_prompt("analyze", analyze_data)
        """
        self.mcp.prompt(name=name)(fn)

    @abstractmethod
    def setup(self) -> None:
        """
        Setup method called during server initialization.

        Subclasses MUST override this to register tools, resources, and prompts.
        Called before the server starts listening for requests.

        Example:
            def setup(self):
                self.add_tool(self.check_stock)
                self.add_tool(self.list_items)
                self.add_resource("stock://{id}", self.get_stock)
        """
        pass

    async def cleanup(self) -> None:
        """
        Cleanup method called during server shutdown.

        Override in subclasses for custom cleanup logic (e.g., closing connections).
        Called after the server stops accepting requests.
        """
        pass

    # ============= Server Lifecycle =============

    @asynccontextmanager
    async def _server_lifecycle(self):
        try:
            self.logger.info("Starting server initialization...")
            self.metrics.start_time = time.time()

            # Call setup hook - subclasses register tools/resources here
            self.setup()

            # Setup metrics endpoint
            self._setup_metrics_endpoint()

            self._is_running = True
            self.logger.info("Server initialization completed successfully")

            yield

        except Exception as e:
            self.logger.error(f"Server initialization failed: {e}")
            raise
        finally:
            self.logger.info("Starting server cleanup...")
            self._is_running = False

            try:
                await asyncio.wait_for(
                    self.cleanup(), timeout=self.config.shutdown_timeout
                )
            except asyncio.TimeoutError:
                self.logger.warning("Cleanup timeout - forcing shutdown")

            self.logger.info("Server cleanup completed")

    async def run_async(self) -> None:
        async with self._server_lifecycle():
            self.logger.info(
                f"Starting {self.config.name} on {self.config.host}:{self.config.port}"
            )

            try:
                await self.mcp.run_streamable_http_async()
            except Exception as e:
                self.logger.error(f"Server runtime error: {e}")
                raise
            finally:
                self.logger.info("Server stopped")

    def run(self) -> None:
        """Run the server synchronously."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            self.logger.info("Server interrupted by user")
        except Exception as e:
            self.logger.error(f"Server failed: {e}")
            raise

    def stop(self) -> None:
        """Stop the running server."""
        if self._is_running:
            self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        return self._is_running
