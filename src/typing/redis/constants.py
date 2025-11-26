from enum import Enum


class RedisChannels:
    # Core channels
    QUERY_CHANNEL = "agent:query_channel"
    TASK_UPDATES = "agent:task_updates"

    # Manage command channel per agent type
    COMMAND_CHANNEL = "agent:command_channel:{}"

    # Notify when a query is completed
    QUERY_COMPLETION = "query:completion:{}"

    # Real-time updates for specific query_id
    QUERY_UPDATES = "query:updates:{}"

    @classmethod
    def get_command_channel(cls, agent_type: str) -> str:
        return cls.COMMAND_CHANNEL.format(agent_type)

    @classmethod
    def get_query_completion_channel(cls, query_id: str) -> str:
        return cls.QUERY_COMPLETION.format(query_id)

    @classmethod
    def get_query_updates_channel(cls, query_id: str) -> str:
        return cls.QUERY_UPDATES.format(query_id)


class RedisKeys:
    # Agent queues
    AGENT_QUEUE = "agent:queue:{}"
    AGENT_PENDING_QUEUE = "agent:pending_queue:{}"

    # Agent status tracking
    AGENT_STATUS = "agent:status"

    # Shared data storage
    SHARED_DATA = "agent:shared_data:{}"

    # Conversation storage (JSON document)
    CONVERSATION = "conversation:{}"

    @classmethod
    def get_agent_queue(cls, agent_type: str) -> str:
        return cls.AGENT_QUEUE.format(agent_type)

    @classmethod
    def get_agent_pending_queue(cls, agent_type: str) -> str:
        return cls.AGENT_PENDING_QUEUE.format(agent_type)

    @classmethod
    def get_shared_data_key(cls, query_id: str) -> str:
        return cls.SHARED_DATA.format(query_id)

    @classmethod
    def get_conversation_key(cls, conversation_id: str) -> str:
        return cls.CONVERSATION.format(conversation_id)


class TaskStatus(str, Enum):
    DONE = "done"
    PENDING = "pending"
    ERROR = "error"
    PROCESSING = "processing"


from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    TOOL_EXECUTION = "tool_execution"
    THINKING = "thinking"
    TASK_UPDATE = "task_update"
    ERROR = "error"


class BroadcastMessage(BaseModel):
    type: MessageType
    data: Dict[str, Any]
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
