from typing import Optional
from pydantic import Field
from .base_response import BaseAgentResponse

class SummaryResponse(BaseAgentResponse):
    conversation_id: str = Field(..., description="The ID of the summarized conversation")
    summary: str = Field(..., description="The generated conversation summary")
    message_count: int = Field(..., description="Number of messages summarized")
    timestamp: str = Field(..., description="ISO timestamp of when the summary was generated")
    error: Optional[str] = Field(None, description="Error message if summarization failed")
