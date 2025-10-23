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
    response: Optional[Dict[str, Any]] = Field(None, description="Final response data")

    # Error response
    error: Optional[str] = Field(None, description="Error message if failed")

    # Basic metadata
    completion_time: datetime = Field(default_factory=datetime.now)

    @classmethod
    def response_success(
        cls,
        query_id: str,
        response: Dict[str, Any],
        conversation_id: Optional[str] = None,
    ) -> "CompletionResponse":
        return cls(
            query_id=query_id,
            status=CompletionStatus.COMPLETED,
            response=response,
            conversation_id=conversation_id,
        )

    @classmethod
    def response_error(
        cls,
        query_id: str,
        error: str,
        conversation_id: Optional[str] = None,
    ) -> "CompletionResponse":
        return cls(
            query_id=query_id,
            status=CompletionStatus.FAILED,
            error=error,
            conversation_id=conversation_id,
        )
