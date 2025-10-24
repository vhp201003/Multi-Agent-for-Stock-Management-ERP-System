from typing import List, Optional, Union

from pydantic import BaseModel, Field

from src.typing.schema.base_schema import BaseSchema


class ToolCallPlan(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to be called")
    parameters: dict = Field(..., description="Parameters required for the tool call")


class ToolCallSchema(BaseSchema):
    tool_calls: Optional[List[Union[ToolCallPlan, str]]] = Field(
        None,
        description="List of tool calls or resource URIs to execute/read in sequence. Tool calls are dicts with tool_name and parameters, resources are strings (URIs).",
    )
