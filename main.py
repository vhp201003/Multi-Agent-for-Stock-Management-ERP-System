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
from src.typing.redis import QueryTask, RedisChannels, RedisKeys
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
    global orchestrator, inventory_agent, inventory_manager, tasks, redis_client

    try:
        orchestrator = OrchestratorAgent()
        inventory_agent = InventoryAgent()
        chat_agent = ChatAgent(redis_host="localhost", redis_port=6379)
        inventory_manager = InventoryManager()
        redis_client = orchestrator.redis

        tasks = [
            asyncio.create_task(orchestrator.start(), name="orchestrator"),
            asyncio.create_task(inventory_agent.start(), name="inventory_agent"),
            asyncio.create_task(chat_agent.start(), name="chat_agent"),
            asyncio.create_task(inventory_manager.start(), name="inventory_manager"),
        ]

        logging.info("All agents and managers started successfully")
        yield

    except Exception as e:
        logger.error(f"Failed to start agents: {e}")
        raise
    finally:
        logger.info("Initiating graceful shutdown...")

        for task in tasks:
            if not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=10.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown timeout - some tasks may not have completed cleanly"
            )

        logging.info("Agents and managers stopped")


app = FastAPI(title="Multi Agent Stock Management System", lifespan=lifespan)


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
            return _create_error_response(
                query_id, "no_agents", "No agents identified for query processing"
            )

        shared_data = await _initialize_query_state(request, orchestration_result)

        # Publish orchestration task with simplified structure
        await _publish_orchestration_task(query_id, orchestration_result)

        # Wait for completion with enhanced error handling
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
    """Enhanced validation with security-focused checks."""
    if not request.query or not request.query.strip():
        return "Query cannot be empty"

    # SECURITY: Prevent DoS attacks
    if len(request.query) > 10000:
        return "Query too long (max 10,000 characters)"

    if not request.query_id or not request.query_id.strip():
        return "Query ID cannot be empty"

    # SECURITY: Validate query_id format to prevent injection
    if not re.match(r"^[a-zA-Z0-9_-]+$", request.query_id):
        return "Invalid query ID format (alphanumeric, underscore, hyphen only)"

    return None


async def _initialize_query_state(
    request: Request, orchestration_result: OrchestratorResponse
) -> SharedData:
    try:
        if not hasattr(request, "conversation_id") or not request.conversation_id:
            request.conversation_id = f"conversation:{request.query_id}"

        sub_query_dict = {}
        task_dependency = orchestration_result.task_dependency

        for agent_type, task_list in task_dependency.nodes.items():
            if task_list:
                sub_query_list = [task.sub_query for task in task_list]
                sub_query_dict[agent_type] = sub_query_list

        shared_data = SharedData(
            original_query=request.query,
            agents_needed=orchestration_result.agents_needed,
            sub_queries=sub_query_dict,
            results={},
            context={},
            llm_usage={},
            status="processing",
            agents_done=[],
            task_graph=task_dependency,
        )

        await save_shared_data(orchestrator.redis, request.query_id, shared_data)

        logger.info(
            f"Initialized shared state for query {request.query_id} with {len(sub_query_dict)} agent types"
        )

    except Exception as e:
        logger.error(f"Failed to initialize query state for {request.query_id}: {e}")
        raise


async def _publish_orchestration_task(
    query_id: str, orchestration_result: OrchestratorResponse
) -> None:
    try:
        sub_query_dict = {}

        for agent_type, task_list in orchestration_result.task_dependency.nodes.items():
            if task_list:
                sub_query_list = [task.sub_query for task in task_list]
                if sub_query_list:
                    sub_query_dict[agent_type] = sub_query_list

        if not sub_query_dict:
            raise ValueError(f"No valid sub-queries found for query {query_id}")

        message = QueryTask(
            query_id=query_id,
            agents_needed=list(sub_query_dict.keys()),
            sub_query=sub_query_dict,
        )

        await orchestrator.publish_channel(RedisChannels.QUERY_CHANNEL, message)

        logger.info(
            f"Published orchestration for {query_id} to {len(sub_query_dict)} agents: {list(sub_query_dict.keys())}"
        )

    except Exception as e:
        logger.error(f"Failed to publish orchestration for {query_id}: {e}")
        raise


async def _wait_for_completion(query_id: str) -> Dict[str, Any]:
    completion_channel = RedisChannels.get_query_completion_channel(query_id)
    pubsub = None

    try:
        pubsub = orchestrator.redis.pubsub()
        await asyncio.wait_for(pubsub.subscribe(completion_channel), timeout=5.0)

        start_time = asyncio.get_event_loop().time()
        max_wait_time = 300.0  # 5 minutes timeout

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    completion_data = json.loads(message["data"])
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Invalid JSON in completion message for {query_id}: {e}"
                    )
                    continue

                if not isinstance(completion_data, dict):
                    logger.warning(f"Invalid completion data type for {query_id}")
                    continue

                if completion_data.get("query_id") == query_id:
                    logger.info(f"Received completion for query {query_id}")
                    return completion_data

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= max_wait_time:
                logger.warning(
                    f"Query {query_id} completion timeout after {elapsed:.1f}s"
                )
                raise asyncio.TimeoutError("Query completion timeout")

        raise asyncio.TimeoutError("Completion stream ended unexpectedly")

    except Exception as e:
        logger.error(f"Error waiting for completion of {query_id}: {e}")
        raise
    finally:
        if pubsub:
            try:
                await asyncio.wait_for(
                    pubsub.unsubscribe(completion_channel), timeout=2.0
                )
                await asyncio.wait_for(pubsub.aclose(), timeout=2.0)

            except Exception as cleanup_error:
                logger.warning(
                    f"Pubsub cleanup timeout/error for {query_id}: {cleanup_error}"
                )
                try:
                    pubsub.connection.disconnect()
                except Exception:
                    pass


def _create_success_response(
    query_id: str, original_query: str, completion_data: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "query_id": query_id,
        "status": "completed",
        "result": {
            "original_query": original_query,
            "final_response": completion_data.get("final_response"),
            "detailed_results": completion_data.get("results", {}),
            "context": completion_data.get("context", {}),
            "llm_usage": completion_data.get("llm_usage", {}),
            "agents_done": completion_data.get("agents_done", []),
            "processing_time": completion_data.get("processing_time"),
            "execution_progress": completion_data.get("execution_progress", {}),
        },
        "metadata": {
            "timestamp": completion_data.get("timestamp", datetime.now().isoformat()),
            "agents_involved": completion_data.get("agents_done", []),
            "total_agents": len(completion_data.get("agents_done", [])),
        },
    }


def _create_error_response(
    query_id: str, error_type: str, message: str
) -> Dict[str, Any]:
    return {
        "query_id": query_id,
        "status": error_type,
        "error": {
            "type": error_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        },
    }


@app.get("/query/{query_id}")
async def get_query_status(query_id: str):
    global orchestrator

    if not re.match(r"^[a-zA-Z0-9_-]+$", query_id):
        raise HTTPException(status_code=400, detail="Invalid query ID format")

    try:
        shared_key = RedisKeys.get_shared_data_key(query_id)
        shared_data_raw = await orchestrator.redis.json().get(shared_key)

        if not shared_data_raw:
            return {
                "query_id": query_id,
                "status": "not_found",
                "message": "Query not found or expired",
            }

        shared_data = SharedData(**shared_data_raw)

        if shared_data.is_complete:
            return {
                "query_id": query_id,
                "status": "completed",
                "result": {
                    "original_query": shared_data.original_query,
                    "results": shared_data.results,
                    "context": shared_data.context,
                    "llm_usage": shared_data.llm_usage,
                    "agents_done": shared_data.agents_done,
                    "execution_progress": shared_data.execution_progress,
                },
                "metadata": {
                    "completion_timestamp": datetime.now().isoformat(),
                    "total_agents": len(shared_data.agents_needed),
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
                    "completion_percentage": (
                        len(shared_data.agents_done)
                        / len(shared_data.agents_needed)
                        * 100
                        if shared_data.agents_needed
                        else 0
                    ),
                    "execution_progress": shared_data.execution_progress,
                },
                "metadata": {
                    "last_updated": datetime.now().isoformat(),
                },
            }

    except Exception as e:
        logger.error(f"Error in get_query_status for {query_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)[:100]}...",
        )


@app.get("/health")
async def health_check():
    try:
        if redis_client:
            await redis_client.ping()
            redis_status = "connected"
        else:
            redis_status = "disconnected"

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "redis": redis_status,
                "agents": len(tasks),
                "active_tasks": sum(1 for task in tasks if not task.done()),
            },
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "degraded",
            "error": str(e)[:100],  # Truncate for security
            "timestamp": datetime.now().isoformat(),
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010, access_log=True, log_level="info")
