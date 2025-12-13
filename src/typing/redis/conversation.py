from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str = Field(..., description="Role of the message sender (user/assistant)")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When message was sent"
    )
    metadata: Optional[dict] = Field(
        default=None, description="Optional metadata (agent_type, query_id, etc.)"
    )


class ConversationData(BaseModel):
    conversation_id: str = Field(..., description="Unique conversation identifier")
    messages: List[Message] = Field(
        default_factory=list, description="Ordered list of messages"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update time"
    )
    max_messages: int = Field(
        default=50, description="Maximum messages to retain (for memory management)"
    )
    summary: Optional[str] = Field(
        default=None, description="AI-generated summary of recent conversations"
    )
    summary_updated_at: Optional[datetime] = Field(
        default=None, description="When summary was last updated"
    )
    user_id: Optional[str] = Field(
        default=None, description="User ID owning this conversation"
    )

    def add_message(
        self, role: str, content: str, metadata: Optional[dict] = None
    ) -> None:
        message = Message(role=role, content=content, metadata=metadata)
        self.messages.append(message)
        self.updated_at = datetime.now()

        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def get_recent_messages(self, limit: Optional[int] = None) -> List[dict]:
        messages = (
            self.messages[-2 * limit :] if limit else self.messages
        )  # 2 * limit because each interaction has user and assistant messages
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    def update_summary(self, summary: str) -> None:
        self.summary = summary
        self.summary_updated_at = datetime.now()
        self.updated_at = datetime.now()
