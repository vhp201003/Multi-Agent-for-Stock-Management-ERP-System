from .base_response import BaseAgentResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

class Query(BaseModel):
    agent_name: str
    sub_query: list[str]

class Dependency(BaseModel):
    agent_name: str
    dependencies: List[str]

class OrchestratorResponse(BaseAgentResponse):
    agent_needed: list[str]
    sub_queries: List[Query]
    dependencies: List[Dependency]