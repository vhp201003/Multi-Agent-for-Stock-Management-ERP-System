from typing import List, Optional

from pydantic import BaseModel, Field

from src.typing.llm_response import BaseAgentResponse


class ToolCallPlan(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to be called")
    parameters: dict = Field(..., description="Parameters required for the tool call")


class ToolCallSchema(BaseAgentResponse):
    tool_calls: Optional[List[ToolCallPlan]] = Field(
        None,
        description="List of tool calls to execute in sequence (for ACTIONS)",
    )
    read_resources: Optional[List[str]] = Field(
        None,
        description="List of resource URIs to read (for DATA FETCHING, e.g., ['stock://levels'])",
    )
