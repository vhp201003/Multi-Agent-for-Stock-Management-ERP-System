import logging
import time
import uuid

from fastapi import FastAPI
from src.agents.orchestrator_agent import OrchestratorAgent
from src.typing import (
    OrchestratorRequest,
    QueryRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
app = FastAPI(title="Multi Agent System")


@app.post("/query")
async def handle_query(request: QueryRequest):
    orchestrator = OrchestratorAgent()
    query_id = f"q_{uuid.uuid4()}"
    return await orchestrator.process(
        OrchestratorRequest(
            query_id=query_id,
            timestamp=time.time(),
            query=request.query,
        )
    )


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
