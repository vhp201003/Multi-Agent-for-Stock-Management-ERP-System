import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.api.lifespan import agent_manager
from src.services.handle_query import (
    QueryValidationError,
)
from src.services.handle_query import (
    handle_query as handle_query_service,
)
from src.typing.redis import (
    RedisChannels,
    RedisKeys,
    SharedData,
)

logger = logging.getLogger(__name__)


class ApprovalResponseRequest(BaseModel):
    """Request model for approval response via REST API"""

    approval_id: str
    query_id: str
    action: str  # 'approve', 'reject', 'modify'
    modified_params: Optional[dict] = None
    reason: Optional[str] = None


async def handle_query(request):
    try:
        return await handle_query_service(request)
    except QueryValidationError as e:
        raise HTTPException(status_code=400, detail=e.message)


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

        # HITL: Create tasks for bidirectional communication
        async def listen_redis():
            """Listen for Redis messages and forward to WebSocket"""
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data_str = message["data"]
                    if isinstance(data_str, bytes):
                        data_str = data_str.decode("utf-8")

                    data = json.loads(data_str)
                    logger.info(
                        f"Update for query_id {query_id}: {data.get('type', 'unknown')}"
                    )
                    await websocket.send_text(json.dumps(data))

        async def listen_websocket():
            """Listen for WebSocket messages (approval responses) and forward to Redis"""
            while True:
                try:
                    message = await websocket.receive_text()
                    data = json.loads(message)

                    # HITL: Handle approval response from frontend
                    if data.get("type") == "approval_response":
                        approval_data = data.get("data", {})
                        approval_channel = RedisChannels.get_approval_response_channel(
                            query_id
                        )

                        logger.info(
                            f"📨 Received approval response from frontend for query_id {query_id}: "
                            f"approval_id={approval_data.get('approval_id')}, "
                            f"action={approval_data.get('action')}"
                        )

                        # Publish to approval response channel for agent to receive
                        await redis_client.publish(
                            approval_channel, json.dumps(approval_data)
                        )
                        logger.info(
                            f"✅ Published approval response to Redis channel: {approval_channel}"
                        )
                    else:
                        logger.debug(
                            f"Received unknown message type from WebSocket: {data.get('type')}"
                        )

                except WebSocketDisconnect:
                    logger.info(f"WebSocket disconnected for query_id: {query_id}")
                    break
                except Exception as e:
                    logger.error(f"Error receiving WebSocket message: {e}")
                    break

        # Run both listeners concurrently
        redis_task = asyncio.create_task(listen_redis())
        ws_task = asyncio.create_task(listen_websocket())

        # Wait for either task to complete (usually WebSocket disconnect)
        done, pending = await asyncio.wait(
            [redis_task, ws_task], return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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


async def handle_approval_response(request: ApprovalResponseRequest):
    """
    REST endpoint to handle approval responses.
    This allows approvals to be sent even when WebSocket is disconnected.
    """
    try:
        redis_client = agent_manager.redis_client
        if not redis_client:
            raise HTTPException(status_code=503, detail="Redis not available")

        # Get approval response channel for the query
        approval_channel = RedisChannels.get_approval_response_channel(request.query_id)

        # Prepare approval data
        approval_data = {
            "approval_id": request.approval_id,
            "query_id": request.query_id,
            "action": request.action,
        }

        if request.modified_params:
            approval_data["modified_params"] = request.modified_params
        if request.reason:
            approval_data["reason"] = request.reason

        # Publish to Redis channel for agent to receive
        await redis_client.publish(approval_channel, json.dumps(approval_data))

        logger.info(
            f"✅ [REST] Published approval response to Redis channel: {approval_channel}, "
            f"approval_id={request.approval_id}, action={request.action}"
        )

        return {
            "status": "success",
            "message": "Approval response submitted successfully",
            "approval_id": request.approval_id,
        }

    except Exception as e:
        logger.error(f"❌ Failed to handle approval response: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to process approval: {str(e)}"
        )
