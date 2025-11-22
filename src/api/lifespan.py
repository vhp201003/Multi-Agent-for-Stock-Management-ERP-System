import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agents.analytics_agent import AnalyticsAgent
from src.agents.chat_agent import ChatAgent
from src.agents.inventory_agent import InventoryAgent
from src.agents.orchestrator_agent import OrchestratorAgent
from src.agents.summary_agent import SummaryAgent
from src.managers.analytics_manager import AnalyticsManager
from src.managers.inventory_manager import InventoryManager

logger = logging.getLogger(__name__)


class AgentManager:
    def __init__(self):
        self.orchestrator: OrchestratorAgent = None
        self.inventory_agent: InventoryAgent = None
        self.chat_agent: ChatAgent = None
        self.summary_agent: SummaryAgent = None
        self.inventory_manager: InventoryManager = None
        self.analytics_agent: AnalyticsAgent = None
        self.analytics_manager: AnalyticsManager = None
        self.tasks: list[asyncio.Task] = []
        self.redis_client = None

    async def start(self):
        try:
            logger.info("Starting all agents and managers...")

            self.orchestrator = OrchestratorAgent()
            self.inventory_agent = InventoryAgent()
            self.chat_agent = ChatAgent()
            self.summary_agent = SummaryAgent()
            self.inventory_manager = InventoryManager()
            self.analytics_agent = AnalyticsAgent()
            self.analytics_manager = AnalyticsManager()
            self.redis_client = self.orchestrator.redis

            self.tasks = [
                asyncio.create_task(self.orchestrator.start(), name="orchestrator"),
                asyncio.create_task(
                    self.inventory_agent.start(), name="inventory_agent"
                ),
                asyncio.create_task(
                    self.inventory_manager.start(), name="inventory_manager"
                ),
                asyncio.create_task(
                    self.analytics_agent.start(), name="analytics_agent"
                ),
                asyncio.create_task(
                    self.analytics_manager.start(),
                    name="analytics_manager",
                ),
                asyncio.create_task(self.chat_agent.start(), name="chat_agent"),
                asyncio.create_task(self.summary_agent.start(), name="summary_agent"),
            ]

            logger.info("All agents and managers started successfully")

        except Exception as e:
            logger.error(f"Failed to start agents: {e}")
            raise

    async def stop(self):
        logger.info("Initiating graceful shutdown...")

        for task in self.tasks:
            if not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(*self.tasks, return_exceptions=True), timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown timeout - some tasks may not have completed cleanly"
            )

        logger.info("Agents and managers stopped")


# Global instance
agent_manager = AgentManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent_manager.start()
    yield
    await agent_manager.stop()
