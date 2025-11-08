import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from src.api.lifespan import agent_manager
from src.typing import Request
from src.typing.redis import RedisChannels, RedisKeys
from src.typing.redis.shared_data import SharedData

logger = logging.getLogger(__name__)


def validate_query_request(request: Request) -> Optional[str]:
    if not request.query or not request.query.strip():
        return "Query cannot be empty"

    if len(request.query) > 10000:
        return "Query too long (max 10,000 characters)"

    # query_id và conversation_id sẽ được frontend quản lý, backend chỉ validate
    if request.query_id and not re.match(r"^[a-zA-Z0-9_-]+$", request.query_id):
        return "Invalid query ID format (alphanumeric, underscore, hyphen only)"

    if request.conversation_id and not re.match(
        r"^[a-zA-Z0-9_-]+$", request.conversation_id
    ):
        return "Invalid conversation ID format (alphanumeric, underscore, hyphen only)"

    return None


async def handle_query(request: Request):
    validation_error = validate_query_request(request)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    try:
        # Backend chỉ xử lý query, không tạo query_id hay conversation_id
        orchestrator = agent_manager.orchestrator
        result = await orchestrator.process_query(request)
        return result
    except Exception as e:
        logger.exception(f"Critical error processing query {request.query_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def websocket_handler(websocket: WebSocket, query_id: str):
    """Handle WebSocket connections for real-time query updates."""
    await websocket.accept()
    redis_client = agent_manager.redis_client
    pubsub = redis_client.pubsub()

    try:
        # Subscribe to the query-specific updates channel
        update_channel = RedisChannels.get_query_updates_channel(query_id)
        await pubsub.subscribe(update_channel)

        logger.info(f"WebSocket connected for query_id: {query_id}")

        async for message in pubsub.listen():
            if message["type"] == "message":
                # Redis decode_responses=True already returns string, no need to decode
                data_str = message["data"]
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")

                data = json.loads(data_str)

                # Send the update directly to the WebSocket client
                logger.info(f"Update for query_id {query_id}: {data}")
                await websocket.send_text(json.dumps(data))

                # Auto-disconnect if query is completed
                if (
                    data.get("status") == "done"
                    and data.get("agent_type") == "chat_agent"
                ):
                    logger.info(f"Query {query_id} completed, closing WebSocket")
                    await websocket.close(code=1000, reason="Query completed")
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for query_id: {query_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket for query_id {query_id}: {e}")
    finally:
        # Unsubscribe from the Redis channel
        await pubsub.unsubscribe(update_channel)
        logger.info(f"WebSocket cleanup completed for query_id: {query_id}")


async def get_query_status(query_id: str):
    if not re.match(r"^[a-zA-Z0-9_-]+$", query_id):
        raise HTTPException(status_code=400, detail="Invalid query ID format")

    try:
        orchestrator = agent_manager.orchestrator
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
            agent_results = {}
            for agent_type in shared_data.agents_needed:
                agent_results[agent_type] = shared_data.get_agent_results(agent_type)

            return {
                "query_id": query_id,
                "status": "completed",
                "result": {
                    "original_query": shared_data.original_query,
                    "agent_results": agent_results,
                    "llm_usage": shared_data.llm_usage,
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


async def health_check():
    """Check the health of the system."""
    try:
        redis_client = agent_manager.redis_client
        tasks = agent_manager.tasks

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
