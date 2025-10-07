import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from src.agents.chat_agent import ChatAgent
from src.agents.inventory_agent import InventoryAgent
from src.agents.orchestrator_agent import OrchestratorAgent
from src.managers.inventory_manager import InventoryManager
from src.typing import OrchestratorResponse, Request
from src.typing.redis import QueryTask
from src.typing.redis.shared_data import SharedData
from src.utils import save_shared_data

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

orchestrator: OrchestratorAgent
inventory_agent: InventoryAgent
chat_agent: ChatAgent
inventory_manager: InventoryManager
tasks: list[asyncio.Task] = []
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the lifespan of the FastAPI application, handling startup and shutdown of agents and managers.

    This async context manager is used as the lifespan handler for the FastAPI app.
    It initializes and starts all necessary agents (OrchestratorAgent, InventoryAgent, ChatAgent) and managers (InventoryManager)
    during application startup, allowing them to run persistently in the background for pub/sub communication.
    During shutdown, it cleanly cancels all background tasks to prevent resource leaks.

    Args:
        app (FastAPI): The FastAPI application instance. Passed automatically by FastAPI's lifespan system.

    Yields:
        None: Yields control back to FastAPI after startup setup, allowing the app to serve requests.
              Code after yield runs during shutdown.

    Startup Process:
        - Initializes global instances of OrchestratorAgent, InventoryAgent, ChatAgent, and InventoryManager.
        - Creates and starts asynchronous tasks for:
          - OrchestratorAgent.start(): Begins listening on pub/sub channels for task updates.
          - InventoryAgent.start(): Begins listening on command channels for inventory task execution.
          - ChatAgent.start(): Begins listening for final response generation commands.
          - InventoryManager.start(): Listens for new queries and manages inventory task distribution.
        - Logs successful startup.

    Shutdown Process:
        - Cancels all running tasks to stop background operations.
        - Awaits task completion with exception handling to ensure clean exit.
        - Logs successful shutdown.

    Note:
        Uses global variables for instances and tasks to allow access across the lifespan.
        InventoryAgent connects to MCP server on localhost:8001 for inventory operations.
        Requires Redis to be running for pub/sub functionality and MCP server for inventory data.
    """
    global orchestrator, inventory_agent, inventory_manager, tasks, redis_client

    orchestrator = OrchestratorAgent()
    inventory_agent = InventoryAgent()  # Uses default MCP server URL from class
    chat_agent = ChatAgent(redis_host="localhost", redis_port=6379)
    inventory_manager = InventoryManager()  # Specific inventory manager
    redis_client = orchestrator.redis  # Use orchestrator's redis client

    tasks = [
        asyncio.create_task(orchestrator.start()),
        asyncio.create_task(inventory_agent.start()),
        asyncio.create_task(chat_agent.start()),
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
    global orchestrator, redis_client

    validation_error = _validate_query_request(request)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    query_id = request.query_id

    try:
        orchestration_result = await asyncio.wait_for(
            orchestrator.process(request), timeout=30.0
        )

        if not orchestration_result or not orchestration_result.agents_needed:
            return {"No agents identified for query processing."}

        shared_data = await _initialize_query_state(request, orchestration_result)

        await _publish_orchestration_task(query_id, orchestration_result, shared_data)

        completion_result = await _wait_for_completion(query_id)

        return _create_success_response(query_id, request.query, completion_result)

    except asyncio.TimeoutError:
        logger.warning(f"Query {query_id} orchestration timeout")
        return _create_error_response(
            query_id, "orchestration_timeout", "Query analysis timed out"
        )

    except Exception as e:
        logger.exception(f"Critical error processing query {query_id}: {e}")
        return _create_error_response(
            query_id, "internal_error", "Query processing failed"
        )


def _validate_query_request(request: Request) -> Optional[str]:
    """Validate request with security-focused checks."""
    if not request.query or not request.query.strip():
        return "Query cannot be empty"

    if len(request.query) > 10000:  # SECURITY: Prevent DoS
        return "Query too long (max 10,000 characters)"

    if not request.query_id or not request.query_id.strip():
        return "Query ID cannot be empty"

    if not re.match(r"^[a-zA-Z0-9_-]+$", request.query_id):
        return "Invalid query ID format"

    return None


async def _initialize_query_state(
    request: Request, orchestration_result: OrchestratorResponse
) -> SharedData:
    if not hasattr(request, "conversation_id") or not request.conversation_id:
        request.conversation_id = f"conversation:{request.query_id}"

    sub_query_dict = {}
    task_dependency = orchestration_result.task_dependency

    for agent_type, agent_node in task_dependency.nodes.items():
        sub_query_list = [task.sub_query for task in agent_node.tasks]
        if sub_query_list:
            sub_query_dict[agent_type] = sub_query_list

    shared_data = SharedData(
        original_query=request.query,
        agents_needed=orchestration_result.agents_needed,
        sub_queries=sub_query_dict,
        results={},
        context={},
        llm_usage={},
        status="processing",
        agents_done=[],  # Explicit initialization
        task_graph=task_dependency,  # Use the actual task dependency graph
    )

    await save_shared_data(orchestrator.redis, request.query_id, shared_data)

    return shared_data


async def _publish_orchestration_task(
    query_id: str, orchestration_result, shared_data: SharedData
) -> None:
    sub_query_dict = {}
    for agent_type, agent_node in orchestration_result.task_dependency.nodes.items():
        sub_query_list = [task.sub_query for task in agent_node.tasks]
        if sub_query_list:
            sub_query_dict[agent_type] = sub_query_list

    message = QueryTask(
        query_id=query_id,
        agent_type=list(sub_query_dict.keys()),
        sub_query=sub_query_dict,
    )

    try:
        await orchestrator.publish_channel("agent:query_channel", message)
        logger.info(
            f"Published orchestration for {query_id} to {len(sub_query_dict)} agents"
        )
    except Exception as e:
        logger.error(f"Failed to publish orchestration for {query_id}: {e}")
        raise


async def _wait_for_completion(query_id: str) -> Dict[str, Any]:
    completion_channel = f"query:completion:{query_id}"
    pubsub = None

    try:
        pubsub = orchestrator.redis.pubsub()
        await pubsub.subscribe(completion_channel)

        start_time = asyncio.get_event_loop().time()
        max_wait_time = 300.0  # 5 minutes

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    completion_data = json.loads(message["data"])

                    if not isinstance(completion_data, dict):
                        logging.warning(f"Invalid completion data type for {query_id}")
                        continue

                    if completion_data.get("query_id") == query_id:
                        logger.info(f"Received completion for query {query_id}")
                        return completion_data

                except json.JSONDecodeError as e:
                    logger.error(
                        f"Invalid JSON in completion message for {query_id}: {e}"
                    )
                    continue

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= max_wait_time:
                logger.warning(
                    f"Query {query_id} completion timeout after {elapsed:.1f}s"
                )
                raise asyncio.TimeoutError("Query completion timeout")

        raise asyncio.TimeoutError("Completion stream ended unexpectedly")

    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe(completion_channel)
                await pubsub.aclose()
            except Exception as e:
                logger.error(f"Error cleaning up pubsub for {query_id}: {e}")


def _create_success_response(
    query_id: str, original_query: str, completion_data: Dict[str, Any]
) -> Dict[str, Any]:
    final_response = completion_data.get("final_response")

    return {
        "query_id": query_id,
        "status": "completed",
        "result": {
            "original_query": original_query,
            "final_response": final_response,  # Primary user-facing response
            "detailed_results": completion_data.get("results", {}),
            "context": completion_data.get("context", {}),
            "llm_usage": completion_data.get("llm_usage", {}),
            "agents_done": completion_data.get("agents_done", []),
            "processing_time": completion_data.get("processing_time"),
        },
        "metadata": {
            "timestamp": completion_data.get("timestamp"),
            "agents_involved": completion_data.get("agents_done", []),
        },
    }


def _create_error_response(
    query_id: str, error_type: str, message: str
) -> Dict[str, Any]:
    return {
        "query_id": query_id,
        "status": error_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/query/{query_id}")
async def get_query_status(query_id: str):
    """Get the status and result of a query by its ID.

    Clients can poll this endpoint to check processing status and get final results.
    """
    global orchestrator

    try:
        shared_key = f"agent:shared_data:{query_id}"
        shared_data_raw = await orchestrator.redis.get(shared_key)

        if not shared_data_raw:
            return {
                "query_id": query_id,
                "status": "not_found",
                "message": "Query not found",
            }

        from src.typing.redis import SharedData

        shared_data = SharedData.model_validate_json(shared_data_raw)

        if shared_data.status == "done":
            return {
                "query_id": query_id,
                "status": "completed",
                "result": {
                    "original_query": shared_data.original_query,
                    "results": shared_data.results,
                    "context": shared_data.context,
                    "llm_usage": shared_data.llm_usage,
                    "agents_done": shared_data.agents_done,
                },
            }
        else:
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
        logger.error(f"Error in get_query_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the service is running."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
