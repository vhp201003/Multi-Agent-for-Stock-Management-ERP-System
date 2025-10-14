from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Request(BaseModel):
    query_id: str
    conversation_id: Optional[str] = None
    query: Optional[str] = None
    timestamp: Optional[datetime] = datetime.now()