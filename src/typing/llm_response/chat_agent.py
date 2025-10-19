from typing import Optional

from src.typing import BaseAgentResponse, ChatAgentSchema


class ChatResponse(BaseAgentResponse):
    result: Optional[ChatAgentSchema] = None
