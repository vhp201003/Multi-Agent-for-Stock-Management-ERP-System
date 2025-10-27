import json
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    model: str
    api_key: str
    mcp_server_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    messages: List[Dict[str, str]] = Field(default_factory=list)


class ConfigManager:
    def __init__(self, profiles_dir: str = "config/profiles", profile: str = "default"):
        self.profiles_dir = profiles_dir
        self.profile = profile
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        profile_file = os.path.join(self.profiles_dir, f"{self.profile}.json")
        if not os.path.exists(profile_file):
            raise FileNotFoundError(f"Profile file {profile_file} not found")

        with open(profile_file, "r") as f:
            return json.load(f)

    def get_agent_config(self, agent_type: str) -> AgentConfig:
        agents = self._config.get("agents", {})
        agent_config = agents.get(agent_type, {})
        return AgentConfig(**agent_config)

    def get_global_setting(self, key: str) -> Any:
        return self._config.get("global_settings", {}).get(key)


# Global config manager
config_manager = ConfigManager(profile=os.environ.get("CONFIG_PROFILE", "default"))


# Convenience functions
def get_agent_config(agent_type: str) -> AgentConfig:
    return config_manager.get_agent_config(agent_type)


def get_redis_host() -> str:
    return config_manager.get_global_setting("redis_host") or "localhost"


def get_redis_port() -> int:
    port_str = config_manager.get_global_setting("redis_port") or "6379"
    try:
        return int(port_str)
    except ValueError:
        return 6379
