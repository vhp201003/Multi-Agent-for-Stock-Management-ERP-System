import asyncio
import logging
from typing import Dict, List

from src.mcp.server.base_server import BaseMCPServer
from src.mcp.server.inventory_server import InventoryMCPServer, InventoryServerConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MCPServerManager:
    def __init__(self):
        self.servers: Dict[str, BaseMCPServer] = {}
        self.tasks: List[asyncio.Task] = []
        self._shutdown = asyncio.Event()

    def add_server(self, name: str, server: BaseMCPServer):
        self.servers[name] = server
        logger.info(f"Added server: {name}")

    async def start_all(self):
        logger.info(f"Starting {len(self.servers)} servers...")

        for name, server in self.servers.items():
            task = asyncio.create_task(server.run_async(), name=f"server_{name}")
            self.tasks.append(task)
            logger.info(f"✅ Started: {name}")

        logger.info("All servers started!")

    async def stop_all(self):
        logger.info("Stopping all servers...")

        self._shutdown.set()

        for name, server in self.servers.items():
            server.stop()
            logger.info(f"⏹️ Stopped: {name}")

        for task in self.tasks:
            if not task.done():
                task.cancel()

        logger.info("All servers stopped!")

    async def wait_until_stopped(self):
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


def create_inventory_server(
    port: int = 8011,
    erpnext_url: str = "http://erp.localhost:8000",
    warehouse: str = "Stores - HP",
) -> InventoryMCPServer:
    """
    Create Inventory MCP Server with ERPNext integration.

    Args:
        port: Server port (default: 8001)
        erpnext_url: ERPNext instance URL
        warehouse: Default warehouse name

    Returns:
        Configured InventoryMCPServer instance
    """
    config = InventoryServerConfig(
        name="InventoryMCPServer",
        host="0.0.0.0",
        port=port,
        debug=True,
        erpnext_url=erpnext_url,
        erpnext_api_key="ba1a625e37f5548",  # TODO: Load from environment or config
        erpnext_api_secret="6f53482b297cc44",  # TODO: Load from environment or config
        default_warehouse=warehouse,
        low_stock_threshold=10,
        critical_stock_threshold=5,
    )
    return InventoryMCPServer(config)


async def run_default_setup():
    manager = MCPServerManager()

    logger.info("🔧 Configuring Inventory MCP Server...")
    inventory_server = create_inventory_server(
        port=8011,
        erpnext_url="http://erp.localhost:8000",
        warehouse="Main Warehouse",
    )
    manager.add_server("inventory", inventory_server)

    try:
        await manager.start_all()
        await manager.wait_until_stopped()

    except KeyboardInterrupt:
        logger.info("\n\n👋 Received shutdown signal")
    except Exception as e:
        logger.error(f"\n\n❌ Server error: {e}", exc_info=True)
    finally:
        await manager.stop_all()
        logger.info("✅ All servers shut down gracefully")


if __name__ == "__main__":
    asyncio.run(run_default_setup())
