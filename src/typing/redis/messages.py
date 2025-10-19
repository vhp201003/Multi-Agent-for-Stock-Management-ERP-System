import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .constants import TaskStatus


class QueryTask(BaseModel):
    query_id: str
    agents_needed: List[str]
    sub_query: Dict[str, List[str]]  # agent_type -> list of sub_queries


class TaskUpdate(BaseModel):
    task_id: str = None
    query_id: str
    sub_query: str
    status: TaskStatus
    result: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    timestamp: str
    llm_usage: Dict[str, Any]
    llm_reasoning: Optional[str] = None
    agent_type: Optional[str] = None  # The agent type that sent this update


class CommandMessage(BaseModel):
    query_id: str
    conversation_id: Optional[str] = None
    agent_type: str
    sub_query: Optional[str] = None
    command: str
    timestamp: str = datetime.now().isoformat()
