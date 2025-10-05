import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from src.agents.orchestrator_agent import OrchestratorAgent
from src.agents.worker_agent import WorkerAgent
from src.managers.base_manager import BaseManager
from src.typing import (
    Request,
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
redis_client = None


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
    global orchestrator, inventory_agent, inventory_manager, tasks, redis_client

    # Initialize agents and managers
    orchestrator = OrchestratorAgent()
    inventory_agent = WorkerAgent(
        "InventoryAgent"
    )  # Assuming InventoryAgent inherits from WorkerAgent
    inventory_manager = BaseManager("InventoryAgent")
    redis_client = orchestrator.redis  # Use orchestrator's redis client

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
async def handle_query(request: Request):
    """Handle incoming query by orchestrating through agents with completion notification.

    This endpoint initiates the query processing pipeline:
    1. Orchestrator analyzes the query and determines required agents/sub-queries
    2. Publishes the orchestration result to Redis for managers to process
    3. Subscribes to completion channel and waits for notification
    4. Returns the final results when all agents complete

    The processing happens asynchronously via Redis pub/sub, and completion is notified via pub/sub.
    """
    global orchestrator, redis_client

    try:
        # Step 1: Get orchestration plan from orchestrator
        orchestration_result = await orchestrator.process(request)

        # Step 2: Transform and publish to Redis for async processing
        # Transform sub_queries from List[Query] to dict format expected by managers
        sub_query_dict = {}
        for query_item in orchestration_result.sub_queries:
            sub_query_dict[query_item.agent_name] = query_item.sub_query

        message = {
            "query_id": request.query_id,
            "original_query": request.query,
            "agent_name": orchestration_result.agent_needed,  # List of agent names
            "sub_query": sub_query_dict,  # Dict: agent_name -> list of sub_queries
            "dependencies": [
                dep.model_dump() for dep in orchestration_result.dependencies
            ],
            "timestamp": request.timestamp.isoformat() if request.timestamp else None,
        }

        # Init shared data using orchestrator's method
        await orchestrator.update_shared_data(
            request.query_id,
            {
                "original_query": request.query,
                "agent_needed": orchestration_result.agent_needed,
                "sub_queries": sub_query_dict,
                "results": {},
                "context": {},
                "llm_usage": {},
                "status": "processing",
                "created_at": request.timestamp.isoformat()
                if request.timestamp
                else None,
            },
        )

        # Publish to query channel using orchestrator's method
        await orchestrator.publish_message("agent:query_channel", message)

        # Step 3: Wait for completion notification via Redis pub/sub
        pubsub = orchestrator.redis.pubsub()
        completion_channel = f"query:completion:{request.query_id}"
        await pubsub.subscribe(completion_channel)

        try:
            max_wait_time = 300  # 5 minutes timeout
            wait_interval = 1  # Check every 1 second for timeout
            elapsed = 0

            async for message in pubsub.listen():
                if message["type"] == "message":
                    completion_data = json.loads(message["data"])

                    # Verify this is the completion for our query
                    if completion_data.get("query_id") == request.query_id:
                        # Query completed, return results
                        return {
                            "query_id": request.query_id,
                            "status": "completed",
                            "result": {
                                "original_query": request.query,
                                "results": completion_data.get("results", {}),
                                "context": completion_data.get("context", {}),
                                "llm_usage": completion_data.get("llm_usage", {}),
                                "agents_done": completion_data.get("agents_done", []),
                            },
                        }

                # Check for timeout
                elapsed += wait_interval
                if elapsed >= max_wait_time:
                    break

            # Timeout
            return {
                "query_id": request.query_id,
                "status": "timeout",
                "message": "Query processing timed out",
            }

        finally:
            await pubsub.unsubscribe(completion_channel)

    except Exception as e:
        logging.error(f"Error in handle_query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/{query_id}")
async def get_query_status(query_id: str):
    """Get the status and result of a query by its ID.

    Clients can poll this endpoint to check processing status and get final results.
    """
    global orchestrator

    try:
        # Check shared data for status
        shared_key = f"agent:shared_data:{query_id}"
        shared_data_raw = await orchestrator.redis.get(shared_key)

        if not shared_data_raw:
            return {
                "query_id": query_id,
                "status": "not_found",
                "message": "Query not found",
            }

        # Parse shared data
        from src.typing.redis import SharedData

        shared_data = SharedData.model_validate_json(shared_data_raw)

        if shared_data.status == "done":
            # Query completed, return results
            return {
                "query_id": query_id,
                "status": "completed",
                "result": {
                    "original_query": shared_data.original_query,
                    "results": shared_data.results,
                    "context": shared_data.context,
                    "llm_usage": shared_data.llm_usage,
                    "agents_done": shared_data.agents_done,
                    "completed_at": shared_data.created_at,  # Could add a completed_at field later
                },
            }
        else:
            # Still processing
            return {
                "query_id": query_id,
                "status": "processing",
                "message": "Query is being processed",
                "progress": {
                    "agents_needed": shared_data.agents_needed,
                    "agents_done": shared_data.agents_done,
                },
            }

    except Exception as e:
        logging.error(f"Error in handle_query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the service is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
