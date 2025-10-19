from typing import Optional

from pydantic import BaseModel

from src.typing.schema.tool_call import ToolCallSchema

from .base_response import BaseAgentResponse


class ToolCallResponse(BaseAgentResponse):
    result: Optional[ToolCallSchema] = None


class ToolCallResultResponse(BaseModel):
    tool_name: str
    tool_result: dict


class ResourceCallResponse(BaseModel):
    resource_name: str
    resource_data: dict


class WorkerAgentProcessResponse(ToolCallResponse):
    tools_result: list[ToolCallResultResponse] = []
    data_resources: list[ResourceCallResponse] = []
