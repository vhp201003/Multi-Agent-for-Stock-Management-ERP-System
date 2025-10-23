from typing import List, Optional

from pydantic import BaseModel, Field

from src.typing.schema.base_schema import BaseSchema


class ToolCallPlan(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to be called")
    parameters: dict = Field(..., description="Parameters required for the tool call")


class ToolCallSchema(BaseSchema):
    tool_calls: Optional[List[ToolCallPlan]] = Field(
        None,
        description="List of tool calls to execute in sequence (for ACTIONS)",
    )
    read_resources: Optional[List[str]] = Field(
        None,
        description="List of resource URIs to read (for DATA FETCHING, e.g., ['stock://levels'])",
    )
