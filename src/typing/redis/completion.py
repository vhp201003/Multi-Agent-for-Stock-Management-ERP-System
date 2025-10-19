from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CompletionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class CompletionResponse(BaseModel):
    query_id: str = Field(..., description="Query identifier")
    conversation_id: Optional[str] = None
    status: CompletionStatus

    # Success response
    response: Optional[str] = Field(None, description="Final response text")
    data: Optional[Dict[str, Any]] = Field(None, description="Structured results")

    # Error response
    error: Optional[str] = Field(None, description="Error message if failed")

    # Basic metadata
    original_query: str = Field(..., description="Original user query")
    completion_time: datetime = Field(default_factory=datetime.now)

    @classmethod
    def response_success(
        cls,
        query_id: str,
        response: str,
        original_query: str,
        data: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
    ) -> "CompletionResponse":
        return cls(
            query_id=query_id,
            status=CompletionStatus.COMPLETED,
            response=response,
            data=data,
            original_query=original_query,
            conversation_id=conversation_id,
        )

    @classmethod
    def response_error(
        cls,
        query_id: str,
        error: str,
        original_query: str,
        conversation_id: Optional[str] = None,
    ) -> "CompletionResponse":
        return cls(
            query_id=query_id,
            status=CompletionStatus.FAILED,
            error=error,
            original_query=original_query,
            conversation_id=conversation_id,
        )
