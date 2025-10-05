from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class QueryTask(BaseModel):
    """Message for agent:query_channel (Orchestrator -> Manager)"""

    query_id: str
    agent_name: List[str]
    sub_query: Dict[str, List[str]]  # agent_name -> list of sub_queries
    previous_context: List[str] = []


class TaskUpdate(BaseModel):
    """Message for agent:task_updates:{agent_name} (Agent -> Manager/Orchestrator)"""

    query_id: str
    sub_query: str
    status: str  # e.g., "done"
    results: Dict[str, Any]  # {sub_query: result}
    context: Dict[str, Any]  # {sub_query: context}
    timestamp: str  # ISO format
    llm_usage: Dict[str, Any]  # e.g., {"tokens": 123, "cost": 0.004}
    update_type: str = "task_completed"


class CommandMessage(BaseModel):
    """Message for agent:command_channel:{agent_name} (Manager -> Agent)"""

    agent_name: str
    command: str  # e.g., "execute"
    query_id: str
    timestamp: str  # ISO format
    sub_query: Optional[str] = None  # Task data for execute commands
