from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None


class SubQueryNode(BaseModel):
    query: str
    status: str  # e.g., "pending", "done"


class AgentNode(BaseModel):
    sub_queries: List[SubQueryNode]


class Graph(BaseModel):
    nodes: Dict[str, AgentNode]  # agent_name -> AgentNode
    edges: List[List[str]]  # e.g., [["inventory", "ordering"]]


class SharedData(BaseModel):
    original_query: str
    agents_needed: List[str]
    agents_done: List[str] = Field(default_factory=list)
    sub_queries: Dict[str, List[str]]  # agent_name -> list of sub_queries
    results: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )  # agent_name -> {sub_query: result}
    context: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )  # agent_name -> {sub_query: context}
    status: str = "pending"
    created_at: str  # ISO format
    llm_usage: Dict[str, LLMUsage] = Field(
        default_factory=dict
    )  # agent_name -> LLMUsage
    graph: Graph
    sumary_previous_query: Optional[str] = None
    previous_query: List[str] = Field(default_factory=list)
