import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from src.agents.orchestrator_agent import OrchestratorAgent
from src.agents.worker_agent import WorkerAgent
from src.managers.base_manager import BaseManager
from src.typing import (
    OrchestratorRequest,
    QueryRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Global variables for agents and managers
orchestrator: OrchestratorAgent
inventory_agent: WorkerAgent
inventory_manager: BaseManager
tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifespan of the FastAPI application, handling startup and shutdown of agents and managers.

    This async context manager is used as the lifespan handler for the FastAPI app.
    It initializes and starts all necessary agents (OrchestratorAgent, WorkerAgent) and managers (BaseManager)
    during application startup, allowing them to run persistently in the background for pub/sub communication.
    During shutdown, it cleanly cancels all background tasks to prevent resource leaks.

    Args:
        app (FastAPI): The FastAPI application instance. Passed automatically by FastAPI's lifespan system.

    Yields:
        None: Yields control back to FastAPI after startup setup, allowing the app to serve requests.
              Code after yield runs during shutdown.

    Startup Process:
        - Initializes global instances of OrchestratorAgent, WorkerAgent (InventoryAgent), and BaseManager.
        - Creates and starts asynchronous tasks for:
          - OrchestratorAgent.start(): Begins listening on pub/sub channels for task updates.
          - WorkerAgent.start(): Begins listening on command channels for task execution.
          - BaseManager.listen_query_channel(): Listens for new queries from orchestrator.
          - BaseManager.distribute_tasks(): Distributes tasks based on dependencies.
          - BaseManager.listen_task_updates(): Listens for task completion updates from workers.
        - Logs successful startup.

    Shutdown Process:
        - Cancels all running tasks to stop background operations.
        - Awaits task completion with exception handling to ensure clean exit.
        - Logs successful shutdown.

    Note:
        Uses global variables for instances and tasks to allow access across the lifespan.
        Assumes WorkerAgent is subclassed for specific agents like InventoryAgent.
        Requires Redis to be running for pub/sub functionality.
    """
    global orchestrator, inventory_agent, inventory_manager, tasks

    # Initialize agents and managers
    orchestrator = OrchestratorAgent()
    inventory_agent = WorkerAgent(
        "InventoryAgent"
    )  # Assuming InventoryAgent inherits from WorkerAgent
    inventory_manager = BaseManager("InventoryAgent")

    # Start agents and managers asynchronously
    tasks = [
        asyncio.create_task(orchestrator.start()),
        asyncio.create_task(inventory_agent.start()),
        asyncio.create_task(inventory_manager.start()),
    ]

    logging.info("Agents and managers started.")
    yield

    # Cleanup: cancel tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logging.info("Agents and managers stopped.")


app = FastAPI(title="Multi Agent System", lifespan=lifespan)


@app.post("/query")
async def handle_query(request: QueryRequest):
    """Handle incoming query requests by processing through the orchestrator."""
    query_id = f"q_{uuid.uuid4()}"
    orchestrator_request = OrchestratorRequest(
        query_id=query_id,
        timestamp=time.time(),
        query=request.query,
    )
    response = await orchestrator.process(orchestrator_request)
    return response


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the service is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
