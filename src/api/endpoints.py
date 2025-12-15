import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.agents.orchestrator_agent import OrchestratorAgent
from src.api.lifespan import agent_manager
from src.services.quick_actions import generate_quick_actions
from src.services.summary import summarize_conversation
from src.typing import Request
from src.typing.redis import (
    CompletionResponse,
    RedisChannels,
    RedisKeys,
    SharedData,
)
from src.typing.schema import ChatAgentSchema, LLMMarkdownField
from src.utils.converstation import save_conversation_message
from src.utils.shared_data_utils import (
    get_shared_data,
)

logger = logging.getLogger(__name__)


class ApprovalResponseRequest(BaseModel):
    """Request model for approval response via REST API"""

    approval_id: str
    query_id: str
    action: str  # 'approve', 'reject', 'modify'
    modified_params: Optional[dict] = None
    reason: Optional[str] = None


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


async def store_completion_metrics(shared_data: SharedData):
    try:
        redis_client = agent_manager.redis_client
        agent_results = {}
        for agent_type in shared_data.agents_needed:
            results = shared_data.get_agent_results(agent_type)
            if results:
                agent_results[agent_type] = results

        # Internal metrics payload
        internal_metrics = {
            "query_id": shared_data.query_id,
            "agent_results": agent_results,
            "llm_usage": {},
        }

        for usage_key, llm_usage in shared_data.llm_usage.items():
            if hasattr(llm_usage, "model_dump"):
                internal_metrics["llm_usage"][usage_key] = llm_usage.model_dump()

        # Store with TTL for monitoring/billing
        metrics_key = f"metrics:{shared_data.query_id}"
        await redis_client.json().set(metrics_key, "$", internal_metrics)
        await redis_client.expire(metrics_key, 86400)  # 24 hours

        logger.debug(f"Stored completion metrics for {shared_data.query_id}")

    except Exception as e:
        logger.error(f"Failed to store completion metrics: {e}")


def ensure_conversation_id(request: Request):
    if not hasattr(request, "conversation_id") or not request.conversation_id:
        request.conversation_id = request.query_id
    return request


async def wait_for_completion(query_id: str) -> ChatAgentSchema:
    completion_channel = RedisChannels.get_query_completion_channel(query_id)
    redis_client = agent_manager.redis_client
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(completion_channel)
    try:
        start_time = datetime.now().timestamp()
        max_wait_time = 300.0  # 5 minutes
        async for message in pubsub.listen():
            if message["type"] == "message":
                chat_result: ChatAgentSchema = ChatAgentSchema.model_validate_json(
                    message["data"]
                )
                return chat_result
            if (datetime.now().timestamp() - start_time) > max_wait_time:
                return ChatAgentSchema(
                    layout=[
                        LLMMarkdownField(
                            content="""
                            Sorry, the request timed out after waiting for 5 minutes.
                            Please try again or contact support if the issue persists.
                            """
                        )
                    ]
                )
    except Exception:
        return ChatAgentSchema(
            layout=[
                LLMMarkdownField(
                    content="""
                    An error occurred while waiting for the completion response.
                    Please try again later.
                    """
                )
            ]
        )
    finally:
        await pubsub.unsubscribe(completion_channel)
        await pubsub.aclose()


async def handle_query(request: Request):
    try:
        request = ensure_conversation_id(request)
        validation_error = validate_query_request(request)

        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        redis_client = agent_manager.redis_client
        orchestrator: OrchestratorAgent = agent_manager.agents.get("orchestrator")
        await orchestrator.process(request)
        chat_result: ChatAgentSchema = await wait_for_completion(request.query_id)
        chat_response_dict: dict = chat_result.model_dump()
        result = CompletionResponse.response_success(
            query_id=request.query_id,
            response=chat_response_dict,
            conversation_id=request.conversation_id,
        )
        if request.conversation_id and result:
            content_dict = {
                k: v for k, v in chat_response_dict.items() if k != "full_data"
            }
            await save_conversation_message(
                redis_client,
                request.conversation_id,
                "user",
                request.query,
            )

            await save_conversation_message(
                redis_client,
                request.conversation_id,
                "assistant",
                json.dumps(content_dict, ensure_ascii=False),
                metadata={
                    "full_data": chat_response_dict.get("full_data"),
                },
            )

        shared_data = await get_shared_data(redis_client, request.query_id)
        await store_completion_metrics(shared_data)

        await summarize_conversation(request.conversation_id)

        await generate_quick_actions(request.conversation_id)

        return result.model_dump()

    except Exception as e:
        result = CompletionResponse.response_error(
            query_id=request.query_id,
            error=f"Internal server error: {str(e)}",
            conversation_id=request.conversation_id,
        )
        logger.exception(f"Critical error processing query {request.query_id}: {e}")
        return result.model_dump()


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
