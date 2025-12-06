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

# Agent configuration: (name, AgentClass, needs_manager, num_workers)
AGENT_CONFIGS: List[Tuple[str, Type, bool, int]] = [
    ("orchestrator", OrchestratorAgent, False, 1),
    ("inventory", InventoryAgent, True, 3),  # 3 worker instances
    ("analytics", AnalyticsAgent, True, 2),  # 2 worker instances
    ("forecasting", ForecastingAgent, True, 2),  # 2 worker instances
    ("ordering", OrderingAgent, True, 3),  # 3 worker instances
    ("chat", ChatAgent, False, 1),
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
            for name, AgentClass, needs_manager, num_workers in AGENT_CONFIGS:
                # Create manager if needed (1 per agent type)
                if needs_manager:
                    manager = create_manager(name)
                    self.managers[name] = manager
                    self.tasks.append(
                        asyncio.create_task(manager.start(), name=f"{name}_manager")
                    )

                # Create worker instances
                for i in range(num_workers):
                    if num_workers == 1:
                        # Single instance: no instance_id needed
                        agent = AgentClass()
                        agent_key = name
                    else:
                        # Multiple instances: add instance_id
                        instance_id = f"{name}_{i + 1}"
                        agent = AgentClass(instance_id=instance_id)
                        agent_key = instance_id

                    self.agents[agent_key] = agent
                    self.tasks.append(
                        asyncio.create_task(agent.start(), name=f"{agent_key}_agent")
                    )

            # Store redis client from first available agent
            self.redis_client = list(self.agents.values())[0].redis

            logger.info(
                f"Started {len(self.agents)} agent instances and {len(self.managers)} managers"
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
