import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Tuple, Type

from fastapi import FastAPI

from src.agents.analytics_agent import AnalyticsAgent
from src.agents.chat_agent import ChatAgent
from src.agents.forecasting_agent import ForecastingAgent
from src.agents.inventory_agent import InventoryAgent
from src.agents.orchestrator_agent import OrchestratorAgent
from src.agents.ordering_agent import OrderingAgent
from src.managers import create_manager

logger = logging.getLogger(__name__)

# Agent configuration: (name, AgentClass, needs_manager)
AGENT_CONFIGS: List[Tuple[str, Type, bool]] = [
    ("orchestrator", OrchestratorAgent, False),
    ("inventory", InventoryAgent, True),
    ("analytics", AnalyticsAgent, True),
    ("forecasting", ForecastingAgent, True),
    ("ordering", OrderingAgent, True),
    ("chat", ChatAgent, False),
]


class AgentManager:
    def __init__(self):
        self.agents: Dict[str, object] = {}
        self.managers: Dict[str, object] = {}
        self.tasks: List[asyncio.Task] = []
        self.redis_client = None

    async def start(self):
        try:
            logger.info("Starting all agents and managers...")

            # Initialize and start agents/managers from config
            for name, AgentClass, needs_manager in AGENT_CONFIGS:
                # Create and store agent
                agent = AgentClass()
                self.agents[name] = agent
                self.tasks.append(
                    asyncio.create_task(agent.start(), name=f"{name}_agent")
                )

                # Create manager if needed
                if needs_manager:
                    manager = create_manager(name)
                    self.managers[name] = manager
                    self.tasks.append(
                        asyncio.create_task(manager.start(), name=f"{name}_manager")
                    )

            # Store redis client from orchestrator
            self.redis_client = self.agents["orchestrator"].redis

            logger.info(
                f"Started {len(self.agents)} agents and {len(self.managers)} managers"
            )

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
