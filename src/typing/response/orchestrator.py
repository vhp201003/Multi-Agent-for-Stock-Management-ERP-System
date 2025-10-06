from typing import List

from src.typing.schema.orchestrator import TaskDependencyGraph

from .base_response import BaseAgentResponse


class OrchestratorResponse(BaseAgentResponse):
    agents_needed: List[str]
    task_dependency: TaskDependencyGraph
