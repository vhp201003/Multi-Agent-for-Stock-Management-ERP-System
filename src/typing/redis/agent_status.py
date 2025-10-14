from enum import Enum


class AgentStatus(str, Enum):
    """Agent status enum for tracking agent state.

    Attributes:
        IDLE: Agent is ready to receive tasks.
        PROCESSING: Agent is currently processing a task.
        ERROR: Agent encountered an error and may need intervention.
    """

    IDLE = "idle"
    PROCESSING = "processing"
    ERROR = "error"
