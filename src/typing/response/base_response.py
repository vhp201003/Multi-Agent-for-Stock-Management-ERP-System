from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class BaseAgentResponse(BaseModel):
    timestamp: datetime = datetime.now()
    query_id: Optional[str] = None
    result: Optional[str] = None  # The response result/output
    context: Optional[Dict[str, Any]] = None  # Additional context data
    llm_usage: Optional[Dict[str, Any]] = None
    llm_reasoning: Optional[str] = None
    error: Optional[str] = None
