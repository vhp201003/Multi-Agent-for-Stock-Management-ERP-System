from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class BaseAgentRequest(BaseModel):
    query_id: str
    timestamp: Optional[datetime] = datetime.now()

class OrchestratorRequest(BaseAgentRequest):
    query: str  # Field riêng cho Orchestrator

class SQLAgentRequest(BaseAgentRequest):
    query: str  # Field riêng cho SQLAgent

class ChatAgentRequest(BaseAgentRequest):
    query: str  # Field riêng cho ChatAgent
    
class QueryRequest(BaseModel):
    query: str