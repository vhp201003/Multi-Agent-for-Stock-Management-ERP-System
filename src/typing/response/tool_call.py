from typing import List, Optional

from pydantic import Field

from src.typing.schema import ToolCallPlan
from src.typing.response import BaseAgentResponse

class ToolCallResponse(BaseAgentResponse):
    tool_calls: Optional[List[ToolCallPlan]] = Field(
        None,
        description="List of tool calls to execute in sequence (for ACTIONS)",
    )
    read_resource: Optional[List[str]] = Field(
        None,
        description="List of resource URIs to read (for DATA FETCHING, e.g., ['stock://levels'])",
    )