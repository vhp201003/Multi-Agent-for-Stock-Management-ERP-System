import logging

import redis.asyncio as redis
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from config.settings import (
    get_cors_origins,
    get_env_bool,
    get_env_str,
    get_redis_host,
    get_redis_port,
    get_server_host,
    get_server_port,
)
from src.api import admin_endpoints, auth_endpoints, conversation_endpoints, endpoints
from src.api.lifespan import lifespan
from src.typing import Request
from src.utils.colored_logging import setup_colored_logging

load_dotenv()

# Setup colored logging
setup_colored_logging(level=logging.INFO)

logger = logging.getLogger(__name__)

app = FastAPI(title="Multi Agent Stock Management System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_endpoints.router)
app.include_router(admin_endpoints.router)


@app.post("/query")
async def query_endpoint(request: Request):
    return await endpoints.handle_query(request)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, query_id: str = Query(...)):
    await endpoints.websocket_handler(websocket, query_id)


@app.get("/query/{query_id}")
async def query_status_endpoint(query_id: str):
    return await endpoints.get_query_status(query_id)


@app.get("/health")
async def health_endpoint():
    return await endpoints.health_check()


@app.post("/approval-response")
async def approval_response_endpoint(request: endpoints.ApprovalResponseRequest):
    """REST endpoint to handle approval responses (alternative to WebSocket)"""
    return await endpoints.handle_approval_response(request)


@app.post("/conversations", response_model=conversation_endpoints.ConversationResponse)
async def create_conversation(
    request: conversation_endpoints.ConversationCreateRequest,
):
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
async def get_conversation(
    conversation_id: str,
    include_messages: bool = Query(False),
    user_id: str = Query(None),
):
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.get_conversation_handler(
            redis_client, conversation_id, user_id, include_messages
        )
    finally:
        await redis_client.aclose()


@app.put(
    "/conversations/{conversation_id}",
    response_model=conversation_endpoints.ConversationResponse,
)
async def update_conversation(
    conversation_id: str,
    request: conversation_endpoints.ConversationUpdateRequest,
    user_id: str = Query(None),
):
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.update_conversation_handler(
            redis_client, conversation_id, request, user_id
        )
    finally:
        await redis_client.aclose()


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user_id: str = Query(None)):
    redis_client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        return await conversation_endpoints.delete_conversation_handler(
            redis_client, conversation_id, user_id
        )
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=get_server_host(),
        port=get_server_port(),
        reload=get_env_bool("RELOAD", True),
        access_log=True,
        log_level=get_env_str("LOG_LEVEL", "info"),
    )
