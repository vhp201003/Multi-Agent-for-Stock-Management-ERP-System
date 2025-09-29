from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class BaseAgentResponse(BaseModel):
    timestamp: datetime = datetime.now()
    query_id: Optional[str] = None
    llm_usage: Optional[Dict[str, Any]] = None
    llm_reasoning: Optional[str] = None
    error: Optional[str] = None
