from typing import List

from src.typing.schema.orchestrator import Dependency, Query

from .base_response import BaseAgentResponse


class OrchestratorResponse(BaseAgentResponse):
    agent_needed: List[str]
    sub_queries: List[Query]
    dependencies: List[Dependency]
