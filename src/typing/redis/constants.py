class RedisChannels:
    # Core channels
    QUERY_CHANNEL = "agent:query_channel"
    TASK_UPDATES = "agent:task_updates"

    # Agent-specific channel templates (use .format() with agent_type)
    COMMAND_CHANNEL = "agent:command_channel:{}"
    TASK_UPDATES_AGENT = "agent:task_updates:{}"

    # Query completion notifications
    QUERY_COMPLETION = "query:completion:{}"

    @classmethod
    def get_command_channel(cls, agent_type: str) -> str:
        return cls.COMMAND_CHANNEL.format(agent_type)

    @classmethod
    def get_task_updates_channel(cls, agent_type: str) -> str:
        return cls.TASK_UPDATES_AGENT.format(agent_type)

    @classmethod
    def get_query_completion_channel(cls, query_id: str) -> str:
        return cls.QUERY_COMPLETION.format(query_id)


class RedisKeys:
    # Agent queues
    AGENT_QUEUE = "agent:queue:{}"
    AGENT_PENDING_QUEUE = "agent:pending_queue:{}"

    # Agent status tracking
    AGENT_STATUS = "agent:status"

    # Shared data storage
    SHARED_DATA = "agent:shared_data:{}"

    @classmethod
    def get_agent_queue(cls, agent_type: str) -> str:
        return cls.AGENT_QUEUE.format(agent_type)

    @classmethod
    def get_agent_pending_queue(cls, agent_type: str) -> str:
        return cls.AGENT_PENDING_QUEUE.format(agent_type)

    @classmethod
    def get_shared_data_key(cls, query_id: str) -> str:
        return cls.SHARED_DATA.format(query_id)


class TaskStatus:
    DONE = "done"
    PENDING = "pending"
    ERROR = "error"
    PROCESSING = "processing"
