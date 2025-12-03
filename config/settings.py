import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class AgentConfig(BaseModel):
    """Agent configuration loaded from profile.

    LLM parameters (model, temperature, top_p, etc.) are defined here and can be
    unpacked directly into LLM API calls using **config.get_llm_params().

    Supports extra LLM params via model_config extra="allow" - any additional
    fields in profile JSON will be captured and passed to LLM API.
    """

    model_config = {"extra": "allow"}  # Allow extra fields from profile JSON

    # Required
    model: str

    # Non-LLM fields (won't be passed to LLM API)
    mcp_server_url: Optional[str] = None
    messages: List[Dict[str, str]] = Field(default_factory=list)

    # Common LLM params with defaults
    temperature: float = 0.7
    max_tokens: Optional[int] = None

    # Fields that should NOT be passed to LLM
    _non_llm_fields: set = {"mcp_server_url", "messages"}

    def get_llm_params(self) -> Dict[str, Any]:
        """Extract ALL LLM parameters for API calls.

        Automatically includes any extra fields from profile (top_p, reasoning_format, etc.)
        Excludes None values and non-LLM fields (mcp_server_url, messages).

        Usage: **config.get_llm_params() in _call_llm()
        """
        params = {}

        # Get all fields (including extras from model_config extra="allow")
        all_fields = self.model_dump()

        for key, value in all_fields.items():
            # Skip non-LLM fields and None values
            if key in self._non_llm_fields or value is None:
                continue
            params[key] = value

        return params


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


config_manager = ConfigManager(profile=os.environ.get("CONFIG_PROFILE", "default"))


def get_agent_config(agent_type: str) -> AgentConfig:
    return config_manager.get_agent_config(agent_type)


def get_redis_host() -> str:
    return get_env_str("REDIS_HOST", "localhost")


def get_redis_port() -> int:
    return get_env_int("REDIS_PORT", 6379)


def get_env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def get_env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


def get_env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key, "").lower()
    if value in ("true", "1", "yes", "on"):
        return True
    elif value in ("false", "0", "no", "off"):
        return False
    return default


def get_env_list(key: str, default: Optional[List[str]] = None) -> List[str]:
    value = os.environ.get(key, "")
    if not value:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_erpnext_url() -> str:
    return get_env_str("ERPNEXT_URL", "http://localhost:8001")


def get_erpnext_api_key() -> str:
    return get_env_str("ERPNEXT_API_KEY", "")


def get_erpnext_api_secret() -> str:
    return get_env_str("ERPNEXT_API_SECRET", "")


def get_server_host() -> str:
    return get_env_str("HOST", "0.0.0.0")


def get_server_port() -> int:
    return get_env_int("PORT", 8010)


def get_cors_origins() -> List[str]:
    return get_env_list(
        "CORS_ORIGINS", ["http://localhost:5173", "http://localhost:5174"]
    )


def get_inventory_server_port() -> int:
    return get_env_int("INVENTORY_SERVER_PORT", 8011)


def get_analytics_server_port() -> int:
    return get_env_int("ANALYTICS_SERVER_PORT", 8012)


def get_forecasting_server_port() -> int:
    return get_env_int("FORECASTING_SERVER_PORT", 8013)


def get_ordering_server_port() -> int:
    return get_env_int("ORDERING_SERVER_PORT", 8014)


def get_low_stock_threshold() -> int:
    return get_env_int("LOW_STOCK_THRESHOLD", 10)


def get_critical_stock_threshold() -> int:
    return get_env_int("CRITICAL_STOCK_THRESHOLD", 5)


def get_default_lookback_days() -> int:
    return get_env_int("DEFAULT_LOOKBACK_DAYS", 30)


def get_default_top_n() -> int:
    return get_env_int("DEFAULT_TOP_N", 10)


def get_pareto_cutoff() -> float:
    return get_env_float("PARETO_CUTOFF", 0.8)


def get_qdrant_host() -> str:
    return get_env_str("QDRANT_HOST", "localhost")


def get_qdrant_port() -> int:
    return get_env_int("QDRANT_PORT", 6333)


def get_qdrant_url() -> Optional[str]:
    url = get_env_str("QDRANT_URL", "")
    return url if url else None


def get_qdrant_api_key() -> Optional[str]:
    key = get_env_str("QDRANT_API_KEY", "")
    return key if key else None
