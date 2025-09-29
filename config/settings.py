REDIS_URL = "redis://localhost:6379"
QUERY_CHANNEL = "query_channel"
RESULT_CHANNEL_TEMPLATE = "result_channel:{agent_name}"
AGENT_NAMES = ["inventory", "forecasting", "ordering"]

from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class AgentConfig(BaseModel):
    model: str = "openai/gpt-oss-20b"
    temperature: float = 0.7
    messages: List[Dict[str, str]] = []  # Default messages, có thể override

class OrchestratorConfig(AgentConfig):
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are an orchestrator agent."}
    ]

class SQLAgentConfig(AgentConfig):
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are a SQL agent for database queries."}
    ]

class ChatAgentConfig(AgentConfig):
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are a chat agent for summarization."}
    ]

# Default configs
DEFAULT_CONFIGS = {
    "OrchestratorAgent": OrchestratorConfig(),
    "SQLAgent": SQLAgentConfig(),
    "ChatAgent": ChatAgentConfig(),
}