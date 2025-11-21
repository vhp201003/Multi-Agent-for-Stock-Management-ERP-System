import asyncio
import logging
from typing import Dict, List

from dotenv import load_dotenv

from config.settings import (
    get_analytics_server_port,
    get_critical_stock_threshold,
    get_default_lookback_days,
    get_default_top_n,
    get_default_warehouse,
    get_erpnext_api_key,
    get_erpnext_api_secret,
    get_erpnext_url,
    get_inventory_server_port,
    get_low_stock_threshold,
    get_pareto_cutoff,
)
from src.mcp.server.analytics_server import AnalyticsMCPServer, AnalyticsServerConfig
from src.mcp.server.base_server import BaseMCPServer
from src.mcp.server.inventory_server import InventoryMCPServer, InventoryServerConfig

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MCPServerManager:
    """Manages lifecycle of multiple MCP servers with graceful shutdown."""

    def __init__(self) -> None:
        self.servers: Dict[str, BaseMCPServer] = {}
        self.tasks: List[asyncio.Task] = []
        self._shutdown = asyncio.Event()

    def add_server(self, name: str, server: BaseMCPServer) -> None:
        """Register a server instance.

        Args:
            name: Unique identifier for the server
            server: Configured MCP server instance

        Raises:
            ValueError: If server name already exists
        """
        if name in self.servers:
            raise ValueError(f"Server '{name}' already registered")

        self.servers[name] = server
        logger.info(f"Added server: {name}")

    async def start_all(self) -> None:
        """Start all registered servers concurrently."""
        if not self.servers:
            logger.warning("No servers registered, nothing to start")
            return

        logger.info(f"Starting {len(self.servers)} servers...")

        for name, server in self.servers.items():
            task = asyncio.create_task(server.run_async(), name=f"server_{name}")
            self.tasks.append(task)
            logger.info(f"✅ Started: {name} on port {server.config.port}")

        logger.info("All servers started!")

    async def stop_all(self) -> None:
        """Stop all servers and cancel tasks gracefully."""
        logger.info("Stopping all servers...")

        self._shutdown.set()

        # Stop servers with error handling
        for name, server in self.servers.items():
            try:
                server.stop()
                logger.info(f"⏹️ Stopped: {name}")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}", exc_info=True)

        # Cancel tasks with timeout
        cancel_tasks = [task for task in self.tasks if not task.done()]
        if cancel_tasks:
            for task in cancel_tasks:
                task.cancel()

            # Wait for cancellation with 5s timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cancel_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Some tasks did not cancel within timeout")

        logger.info("All servers stopped!")

    async def wait_until_stopped(self) -> None:
        """Wait for all server tasks to complete."""
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


def create_inventory_server(
    port: int | None = None,
    erpnext_url: str | None = None,
    erpnext_api_key: str | None = None,
    erpnext_api_secret: str | None = None,
    warehouse: str | None = None,
    low_stock_threshold: int | None = None,
    critical_stock_threshold: int | None = None,
) -> InventoryMCPServer:
    """Create Inventory MCP Server with ERPNext integration.

    Args:
        port: Server port (defaults to environment variable or 8011)
        erpnext_url: ERPNext instance URL (defaults to environment variable)
        erpnext_api_key: API authentication key (defaults to environment variable)
        erpnext_api_secret: API authentication secret (defaults to environment variable)
        warehouse: Default warehouse name (defaults to environment variable)
        low_stock_threshold: Low stock alert threshold (defaults to environment variable)
        critical_stock_threshold: Critical stock alert threshold (defaults to environment variable)

    Returns:
        Configured InventoryMCPServer instance
    """
    config = InventoryServerConfig(
        name="InventoryMCPServer",
        host="0.0.0.0",
        port=port or get_inventory_server_port(),
        debug=True,
        erpnext_url=erpnext_url or get_erpnext_url(),
        erpnext_api_key=erpnext_api_key or get_erpnext_api_key(),
        erpnext_api_secret=erpnext_api_secret or get_erpnext_api_secret(),
        default_warehouse=warehouse or get_default_warehouse(),
        low_stock_threshold=low_stock_threshold or get_low_stock_threshold(),
        critical_stock_threshold=critical_stock_threshold
        or get_critical_stock_threshold(),
    )
    return InventoryMCPServer(config)


def create_analytics_server(
    port: int | None = None,
    erpnext_url: str | None = None,
    erpnext_api_key: str | None = None,
    erpnext_api_secret: str | None = None,
    default_lookback_days: int | None = None,
    default_top_n: int | None = None,
    pareto_cutoff: float | None = None,
) -> AnalyticsMCPServer:
    """Create Analytics MCP Server with ERPNext integration.

    Args:
        port: Server port (defaults to environment variable or 8012)
        erpnext_url: ERPNext instance URL (defaults to environment variable)
        erpnext_api_key: API authentication key (defaults to environment variable)
        erpnext_api_secret: API authentication secret (defaults to environment variable)
        default_lookback_days: Default analysis period in days (defaults to environment variable)
        default_top_n: Default number of items to return (defaults to environment variable)
        pareto_cutoff: Pareto analysis cutoff percentage (defaults to environment variable)

    Returns:
        Configured AnalyticsMCPServer instance
    """
    config = AnalyticsServerConfig(
        name="AnalyticsMCPServer",
        host="0.0.0.0",
        port=port or get_analytics_server_port(),
        debug=True,
        erpnext_url=erpnext_url or get_erpnext_url(),
        erpnext_api_key=erpnext_api_key or get_erpnext_api_key(),
        erpnext_api_secret=erpnext_api_secret or get_erpnext_api_secret(),
        default_lookback_days=default_lookback_days or get_default_lookback_days(),
        default_top_n=default_top_n or get_default_top_n(),
        pareto_cutoff=pareto_cutoff or get_pareto_cutoff(),
    )
    return AnalyticsMCPServer(config)


async def run_default_setup() -> None:
    """Main entry point: configure and run all MCP servers.

    Configuration is loaded from environment variables (see .env.example).
    Default ports:
        - Inventory Server: 8011
        - Analytics Server: 8012
    """
    manager = MCPServerManager()

    try:
        # Register Inventory Server
        logger.info("🔧 Configuring Inventory MCP Server...")
        inventory_server = create_inventory_server()
        manager.add_server("inventory", inventory_server)

        # Register Analytics Server
        logger.info("🔧 Configuring Analytics MCP Server...")
        analytics_server = create_analytics_server()
        manager.add_server("analytics", analytics_server)

        # Start all servers
        await manager.start_all()
        await manager.wait_until_stopped()

    except KeyboardInterrupt:
        logger.info("\n\n👋 Received shutdown signal (Ctrl+C)")
    except Exception as e:
        logger.error(f"\n\n❌ Server error: {e}", exc_info=True)
        raise
    finally:
        await manager.stop_all()
        logger.info("✅ All servers shut down gracefully")


if __name__ == "__main__":
    asyncio.run(run_default_setup())
