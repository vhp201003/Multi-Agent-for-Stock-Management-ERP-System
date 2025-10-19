from enum import Enum


class AgentStatus(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
