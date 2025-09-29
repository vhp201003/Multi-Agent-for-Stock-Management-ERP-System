from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

class BaseAgentResponse(BaseModel):
    timestamp: Optional[datetime] = datetime.now() 
    error: Optional[str] = None  # Field chung cho errors