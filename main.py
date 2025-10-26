import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from src.agents.chat_agent import ChatAgent
from src.agents.inventory_agent import InventoryAgent
from src.agents.orchestrator_agent import OrchestratorAgent
from src.agents.summary_agent import SummaryAgent
from src.managers.inventory_manager import InventoryManager
from src.typing import Request
from src.typing.redis import RedisKeys
from src.typing.redis.shared_data import SharedData

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


orchestrator: OrchestratorAgent
inventory_agent: InventoryAgent
chat_agent: ChatAgent
summary_agent: SummaryAgent
inventory_manager: InventoryManager
tasks: list[asyncio.Task] = []
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global \
        orchestrator, \
        inventory_agent, \
        inventory_manager, \
        summary_agent, \
        tasks, \
        redis_client

    try:
        orchestrator = OrchestratorAgent()
        inventory_agent = InventoryAgent()
        chat_agent = ChatAgent()
        summary_agent = SummaryAgent()
        inventory_manager = InventoryManager()
        redis_client = orchestrator.redis

        tasks = [
            asyncio.create_task(orchestrator.start(), name="orchestrator"),
            asyncio.create_task(inventory_agent.start(), name="inventory_agent"),
            asyncio.create_task(chat_agent.start(), name="chat_agent"),
            asyncio.create_task(summary_agent.start(), name="summary_agent"),
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
    global orchestrator

    validation_error = _validate_query_request(request)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    try:
        result = await orchestrator.process_query(request)
        return result
    except Exception as e:
        logger.exception(f"Critical error processing query {request.query_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _validate_query_request(request: Request) -> Optional[str]:
    if not request.query or not request.query.strip():
        return "Query cannot be empty"

    if len(request.query) > 10000:
        return "Query too long (max 10,000 characters)"

    if not request.query_id or not request.query_id.strip():
        return "Query ID cannot be empty"

    if not re.match(r"^[a-zA-Z0-9_-]+$", request.query_id):
        return "Invalid query ID format (alphanumeric, underscore, hyphen only)"

    return None


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
