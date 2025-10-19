from typing import Optional

from src.typing.schema.orchestrator import OrchestratorSchema

from .base_response import BaseAgentResponse


class OrchestratorResponse(BaseAgentResponse):
    result: Optional[OrchestratorSchema] = None