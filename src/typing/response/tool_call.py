"""Pydantic models for WorkerAgent tool call responses."""

from typing import Any, Dict, List, Optional

from pydantic import Field

from src.typing.schema import BaseSchema


class ToolCallPlan(BaseSchema):
    """Single tool call plan returned by LLM.

    Used within ToolCallResponse schema for Groq structured output.
    The LLM reasoning will be extracted separately via llm_reasoning field.
    """

    tool_name: str = Field(
        ...,
        description="Name of the tool to call (must match available MCP tool names)",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters to pass to the tool as key-value pairs",
    )


class ToolCallResponse(BaseSchema):
    """Response for tool calls, resource reads, or error case.

    Used as response_schema for Groq. LLM can return:
    - tool_calls: List of tools to execute (actions)
    - read_resource: List of resource URIs to read (data fetching)
    - error: Error message if query cannot be handled

    At least one field must be populated (or error if nothing applicable).
    """

    tool_calls: Optional[List[ToolCallPlan]] = Field(
        None,
        description="List of tool calls to execute in sequence (for ACTIONS)",
    )
    read_resource: Optional[List[str]] = Field(
        None,
        description="List of resource URIs to read (for DATA FETCHING, e.g., ['stock://levels'])",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if query cannot be handled with available tools/resources",
    )


class WorkerProcessResult(BaseSchema):
    """Final result after WorkerAgent processes a sub-query.

    Contains tool execution results, resource read results, LLM reasoning, and usage stats.
    This is NOT used as response_schema (Groq doesn't return this).
    It's built manually after tool/resource execution.
    """

    tool_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Results from executing each tool call",
    )
    resource_results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Results from reading each resource URI",
    )
    llm_reasoning: Optional[str] = Field(
        None,
        description="LLM reasoning extracted from response (if available)",
    )
    llm_usage: Optional[Dict[str, Any]] = Field(
        None,
        description="Token usage statistics from LLM call",
    )
    error: Optional[str] = Field(
        None,
        description="Error message if processing failed",
    )
