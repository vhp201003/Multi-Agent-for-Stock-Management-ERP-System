from typing import Optional

from src.typing.llm_response.base_response import BaseAgentResponse
from src.typing.schema.chat_agent import ChatAgentSchema


class ChatResponse(BaseAgentResponse):
    result: Optional[ChatAgentSchema] = None
