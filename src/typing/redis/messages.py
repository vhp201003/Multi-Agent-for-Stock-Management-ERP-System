from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .constants import TaskStatus


class BaseMessage(BaseModel):
    pass


class QueryTask(BaseMessage):
    query_id: str
    agents_needed: List[str]
    sub_query: Dict[str, List[str]]  # agent_type -> list of sub_queries


class TaskUpdate(BaseMessage):
    timestamp: datetime = Field(default_factory=datetime.now)
    task_id: Optional[str] = None
    query_id: str
    sub_query: str
    status: TaskStatus
    result: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    llm_usage: Dict[str, Any]
    llm_reasoning: Optional[str] = None
    agent_type: Optional[str] = None  # The agent type that sent this update
    instance_id: Optional[str] = None  # Worker instance that processed this task


class CommandMessage(BaseMessage):
    query_id: str
    conversation_id: Optional[str] = None
    agent_type: str
    sub_query: Optional[str] = None
    command: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
