import logging

import redis.asyncio as redis
from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_cors_origins, get_redis_host, get_redis_port
from src.api import conversation_endpoints, endpoints
from src.api.lifespan import lifespan
from src.typing import Request

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Create FastAPI app with lifespan management
app = FastAPI(title="Multi Agent Stock Management System", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/query")
async def query_endpoint(request: Request):
    """Handle query requests."""
    return await endpoints.handle_query(request)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, query_id: str = Query(...)):
    """WebSocket endpoint for real-time query updates."""
    await endpoints.websocket_handler(websocket, query_id)


@app.get("/query/{query_id}")
async def query_status_endpoint(query_id: str):
    """Get query status by query_id."""
    return await endpoints.get_query_status(query_id)


@app.get("/health")
async def health_endpoint():
    """Health check endpoint."""
    return await endpoints.health_check()


# Conversation Management Endpoints
@app.post("/conversations", response_model=conversation_endpoints.ConversationResponse)
async def create_conversation(
    request: conversation_endpoints.ConversationCreateRequest,
):
    """Create a new conversation."""
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.create_conversation_handler(
            redis_client, request
        )
    finally:
        await redis_client.aclose()


@app.get(
    "/conversations", response_model=conversation_endpoints.ConversationListResponse
)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    """List all conversations with pagination."""
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.list_conversations_handler(
            redis_client, limit, offset
        )
    finally:
        await redis_client.aclose()


@app.get(
    "/conversations/{conversation_id}",
    response_model=conversation_endpoints.ConversationResponse,
)
async def get_conversation(conversation_id: str, include_messages: bool = Query(False)):
    """Get a single conversation by ID."""
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.get_conversation_handler(
            redis_client, conversation_id, include_messages
        )
    finally:
        await redis_client.aclose()


@app.put(
    "/conversations/{conversation_id}",
    response_model=conversation_endpoints.ConversationResponse,
)
async def update_conversation(
    conversation_id: str, request: conversation_endpoints.ConversationUpdateRequest
):
    """Update conversation title."""
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.update_conversation_handler(
            redis_client, conversation_id, request
        )
    finally:
        await redis_client.aclose()


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.delete_conversation_handler(
            redis_client, conversation_id
        )
    finally:
        await redis_client.aclose()
