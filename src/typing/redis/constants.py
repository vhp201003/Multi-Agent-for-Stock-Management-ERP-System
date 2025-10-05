class RedisChannels:
    """Redis channel patterns and names used across the multi-agent system."""

    # Core channels
    QUERY_CHANNEL = "agent:query_channel"
    TASK_UPDATES = "agent:task_updates"

    # Agent-specific channel templates (use .format() with agent_name)
    COMMAND_CHANNEL = "agent:command_channel:{}"
    TASK_UPDATES_AGENT = "agent:task_updates:{}"

    # Query completion notifications
    QUERY_COMPLETION = "query:completion:{}"

    @classmethod
    def get_command_channel(cls, agent_name: str) -> str:
        """Get command channel for specific agent."""
        return cls.COMMAND_CHANNEL.format(agent_name)

    @classmethod
    def get_task_updates_channel(cls, agent_name: str) -> str:
        """Get task updates channel for specific agent."""
        return cls.TASK_UPDATES_AGENT.format(agent_name)

    @classmethod
    def get_query_completion_channel(cls, query_id: str) -> str:
        """Get query completion channel for specific query."""
        return cls.QUERY_COMPLETION.format(query_id)


class RedisKeys:
    """Redis key patterns used for data storage."""

    # Agent queues
    AGENT_QUEUE = "agent:queue:{}"
    AGENT_PENDING_QUEUE = "agent:pending_queue:{}"

    # Agent status tracking
    AGENT_STATUS = "agent:status"

    # Shared data storage
    SHARED_DATA = "agent:shared_data:{}"

    @classmethod
    def get_agent_queue(cls, agent_name: str) -> str:
        """Get active queue key for specific agent."""
        return cls.AGENT_QUEUE.format(agent_name)

    @classmethod
    def get_agent_pending_queue(cls, agent_name: str) -> str:
        """Get pending queue key for specific agent."""
        return cls.AGENT_PENDING_QUEUE.format(agent_name)

    @classmethod
    def get_shared_data_key(cls, query_id: str) -> str:
        """Get shared data key for specific query."""
        return cls.SHARED_DATA.format(query_id)


class TaskStatus:
    """Task status constants."""

    DONE = "done"
    PENDING = "pending"
    ERROR = "error"
    PROCESSING = "processing"
