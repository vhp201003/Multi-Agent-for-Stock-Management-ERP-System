import os
from fastapi import FastAPI
from src.agents.orchestrator_agent import OrchestratorAgent
from src.typing import (
    QueryRequest, 
    AgentResponse,
    OrchestratorRequest,
    OrchestratorResponse
)
from dotenv import load_dotenv
import uuid

load_dotenv()
app = FastAPI(title="Multi Agent System")

@app.post("/query", response_model=AgentResponse)
async def handle_query(request: QueryRequest):
    orchestrator = OrchestratorAgent("Orchestrator", llm_api_key=os.environ.get("GROQ_API_KEY"))
    query_id = f"q_{uuid.uuid4()}"
    return await orchestrator.process(OrchestratorRequest(query=request.query, query_id=query_id))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)