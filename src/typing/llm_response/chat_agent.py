from typing import Optional

from src.typing.schema.chat_agent import ChatAgentSchema


class ChatAgentResponse(ChatAgentSchema):
    full_data: Optional[dict] = None
