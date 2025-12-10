from datetime import datetime
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class RedisChannels:
    # Core channels
    QUERY_CHANNEL = "agent:query_channel"  # Orchestrator → Managers (new queries)
    TASK_UPDATES = "agent:task_updates"  # Workers → Orchestrator (task completion)

    # Control signal channel per agent type (stop, reload, etc.)
    # Worker Pull Model: NOT used for task dispatch anymore, only control signals
    COMMAND_CHANNEL = "agent:command_channel:{}"

    # Query completion notification
    QUERY_COMPLETION = "query:completion:{}"  # Orchestrator → API (final response)

    # Real-time progress updates for specific query_id
    QUERY_UPDATES = "query:updates:{}"  # All agents → Frontend (progress, tools, thinking)

    # HITL: Approval response channel (frontend → agent)
    APPROVAL_RESPONSE = "approval:response:{}"  # Frontend → Worker (approval decision)

    @classmethod
    def get_command_channel(cls, agent_type: str) -> str:
        return cls.COMMAND_CHANNEL.format(agent_type)

    @classmethod
    def get_query_completion_channel(cls, query_id: str) -> str:
        return cls.QUERY_COMPLETION.format(query_id)

    @classmethod
    def get_query_updates_channel(cls, query_id: str) -> str:
        return cls.QUERY_UPDATES.format(query_id)

    @classmethod
    def get_approval_response_channel(cls, query_id: str) -> str:
        """Channel for frontend to send approval responses back to agent"""
        return cls.APPROVAL_RESPONSE.format(query_id)


class RedisKeys:
    # Agent queues (Worker Pull Model)
    AGENT_QUEUE = "agent:queue:{}"  # Active tasks - workers BLPOP from here
    AGENT_PENDING_QUEUE = "agent:pending_queue:{}"  # Tasks waiting for dependencies

    # Agent status tracking (legacy single-instance)
    AGENT_STATUS = "agent:status"

    # Multi-instance status tracking: Hash per agent_type
    # Key: agent:status:{agent_type}, Field: instance_id, Value: status
    AGENT_INSTANCE_STATUS = "agent:status:{}"

    # Shared data storage (JSON document)
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

    @classmethod
    def get_agent_instance_status_key(cls, agent_type: str) -> str:
        """Get hash key for tracking all instances of an agent type.

        Hash structure:
          Key: agent:status:{agent_type}
          Fields: {instance_id: status, instance_id: status, ...}
        """
        return cls.AGENT_INSTANCE_STATUS.format(agent_type)


class TaskStatus(str, Enum):
    # Task lifecycle states
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"  # Used in TaskUpdate broadcasts
    COMPLETED = "completed"  # Used in SharedData internal state
    ERROR = "error"
    FAILED = "failed"  # Alias for ERROR in SharedData context
    PENDING_APPROVAL = "pending_approval"  # HITL: Waiting for user approval


class MessageType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    TOOL_EXECUTION = "tool_execution"
    THINKING = "thinking"
    TASK_UPDATE = "task_update"
    ERROR = "error"
    # HITL: Approval workflow messages
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"


class BroadcastMessage(BaseModel):
    type: MessageType
    data: Dict[str, Any]
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
