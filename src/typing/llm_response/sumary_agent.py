from typing import Optional

from src.typing.schema.summary_agent import SummaryAgentSchema

from .base_response import BaseAgentResponse


class SummaryResponse(BaseAgentResponse):
    result: Optional[SummaryAgentSchema] = None
