import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from .base_response import BaseAgentResponse


class ToolCallResponse(BaseAgentResponse):
    # result contains dict with "tool_calls" (list of ChatCompletionMessageToolCall)
    # and "content" (str) from Groq response
    # Not validated against ToolCallSchema to allow raw Groq tool_calls
    result: Optional[Any] = None


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
