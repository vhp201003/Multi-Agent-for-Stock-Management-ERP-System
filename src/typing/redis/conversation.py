from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Individual message in conversation history."""
    role: str = Field(..., description="Role of the message sender (user/assistant)")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now, description="When message was sent")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata (agent_name, query_id, etc.)")


class ConversationData(BaseModel):
    """Complete conversation history for a session."""
    conversation_id: str = Field(..., description="Unique conversation identifier")
    messages: List[Message] = Field(default_factory=list, description="Ordered list of messages")
    created_at: datetime = Field(default_factory=datetime.now, description="Conversation creation time")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update time")
    max_messages: int = Field(default=50, description="Maximum messages to retain (for memory management)")
    
    def add_message(self, role: str, content: str, metadata: Optional[dict] = None) -> None:
        """Add a new message to the conversation."""
        message = Message(role=role, content=content, metadata=metadata)
        self.messages.append(message)
        self.updated_at = datetime.now()
        
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
    
    def get_recent_messages(self, limit: Optional[int] = None) -> List[dict]:
        """Get recent messages in LLM-compatible format."""
        messages = self.messages[-limit:] if limit else self.messages
        return [{"role": msg.role, "content": msg.content} for msg in messages]