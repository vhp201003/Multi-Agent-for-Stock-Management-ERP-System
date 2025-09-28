from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

class BaseAgentResponse(BaseModel):
    query_id: str
    timestamp: Optional[datetime] = None  # Field chung, auto-set nếu cần
    error: Optional[str] = None  # Field chung cho errors

class OrchestratorResponse(BaseAgentResponse):
    response: Dict[str, Any]  # Field riêng: {"text": "..."} hoặc {"error": "..."}

class SQLAgentResponse(BaseAgentResponse):
    sql_result: List[Dict[str, Any]]  # Field riêng: list of DB rows

class ChatAgentResponse(BaseAgentResponse):
    summary: str  # Field riêng: summary text
    
class AgentResponse(BaseModel):
    query_id: str
    response: Dict[str, Any]
    
class IntentResponse(BaseModel):
    intents: List[str]