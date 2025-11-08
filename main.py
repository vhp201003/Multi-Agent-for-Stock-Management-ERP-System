import logging

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from src.api import endpoints
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
    allow_origins=["http://localhost:5173", "http://localhost:5174"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
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
