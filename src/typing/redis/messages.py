from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class QueryTask(BaseModel):
    query_id: str
    agent_type: List[str]
    sub_query: Dict[str, List[str]]  # agent_type -> list of sub_queries


class TaskUpdate(BaseModel):
    query_id: str
    sub_query: str
    status: str
    results: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    timestamp: str
    llm_usage: Dict[str, Any]


class CommandMessage(BaseModel):
    agent_type: str
    command: str  # e.g., "execute"
    query_id: str
    timestamp: str  # ISO format
    sub_query: Optional[str] = None  # Task data for execute commands
