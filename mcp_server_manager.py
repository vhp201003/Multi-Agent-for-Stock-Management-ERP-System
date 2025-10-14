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
    port: int = 8001, warehouse: str = "MAIN-WH"
) -> InventoryMCPServer:
    config = InventoryServerConfig(
        name="InventoryMCP",
        port=port,
        debug=True,
        default_warehouse=warehouse,
    )
    return InventoryMCPServer(config)


async def run_default_setup():
    manager = MCPServerManager()

    inventory_server = create_inventory_server()
    manager.add_server("inventory", inventory_server)

    try:
        await manager.start_all()

        print("\n🚀 Servers are running. Press Ctrl+C to stop.\n")
        await manager.wait_until_stopped()

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(run_default_setup())
