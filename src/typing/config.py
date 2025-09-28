from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class AgentConfig(BaseModel):
    model: str = "llama-3.1-8b-instant"
    temperature: float = 0.7
    max_tokens: int = 150
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