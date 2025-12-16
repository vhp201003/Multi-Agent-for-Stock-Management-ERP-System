import uuid

from pydantic import BaseModel, Field

from .base_response import BaseAgentResponse


class ToolCallResultResponse(BaseModel):
    tool_name: str
    parameters: dict
    tool_result: dict
    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ResourceCallResponse(BaseModel):
    resource_name: str
    resource_result: dict
    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class WorkerAgentProcessResponse(BaseAgentResponse):
    tools_result: list[ToolCallResultResponse] = []
    data_resources: list[ResourceCallResponse] = []
