"""MCP Server for InventoryAgent. Exposes inventory-related tools and resources."""

import logging
from datetime import datetime

from src.typing.mcp import CheckStockOutput, StockLevelsOutput

from .base_server import BaseMCPServer

logger = logging.getLogger(__name__)


class InventoryMCPServer(BaseMCPServer):
    """MCP Server for InventoryAgent.

    Exposes tools and resources for inventory management operations.
    Tools allow querying stock levels, while resources provide overview data.

    Example:
        server = InventoryMCPServer(port=8002)
        server.run()  # Start in separate thread
    """

    def __init__(self, port: int = 8002, debug: bool = False):
        """Initialize InventoryMCPServer.

        Args:
            port (int): Port number for the server. Defaults to 8002.
            debug (bool): Enable debug logging. Defaults to False.
        """
        super().__init__(name="InventoryMCP", port=port, debug=debug)

    def _register_tools(self):
        """Register inventory tools.

        Tools:
            - check_stock: Check current stock level for a product in a warehouse.
        """

        @self.mcp.tool(
            name="check_stock",
            description="Check current stock level for a product in a warehouse. Returns stock availability status.",
            annotations={"category": "inventory", "icon": "📦"},
        )
        async def check_stock(
            product_id: str, warehouse: str = "default"
        ) -> CheckStockOutput:
            """Check stock level for a product.

            Args:
                product_id (str): Product ID to check.
                warehouse (str): Warehouse name. Defaults to "default".

            Returns:
                CheckStockOutput: Structured output with stock information.
            """
            logger.info(
                f"Checking stock for product_id={product_id}, warehouse={warehouse}"
            )
            # TODO: Replace with actual ERPNext query
            stock_level = 100  # Mock data
            status = (
                "available"
                if stock_level > 10
                else "low"
                if stock_level > 0
                else "out_of_stock"
            )
            return CheckStockOutput(
                product_id=product_id,
                stock_level=stock_level,
                warehouse=warehouse,
                status=status,
            )

    def _register_resources(self):
        """Register inventory resources.

        Resources:
            - stock://levels: Overview of current stock levels across all products.
        """

        @self.mcp.resource(
            uri="stock://levels",
            name="Stock Levels Overview",
            description="Provides an overview of current stock levels for all products in a warehouse",
            mime_type="application/json",
        )
        async def get_stock_levels() -> str:
            """Return JSON of stock levels overview.

            Returns:
                str: JSON string containing stock levels data.
            """
            logger.info("Fetching stock levels overview")
            # TODO: Replace with actual DB query
            output = StockLevelsOutput(
                levels={"item1": 100, "item2": 50, "item3": 0},
                timestamp=datetime.now().isoformat(),
                warehouse="default",
            )
            return output.model_dump_json()
