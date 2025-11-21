import logging
from typing import Optional

from groq import AsyncGroq

from config.settings import get_env_str

logger = logging.getLogger(__name__)

_llm_instance: Optional["GroqLLMManager"] = None
_lock = __import__("threading").Lock()


def get_groq_client() -> "GroqLLMManager":
    global _llm_instance

    if _llm_instance is not None:
        return _llm_instance

    with _lock:
        if _llm_instance is not None:
            return _llm_instance
        try:
            logger.debug("Initializing Groq LLM client")
            _llm_instance = GroqLLMManager()
            return _llm_instance

        except Exception as e:
            logger.error(f"✗ Groq LLM initialization failed: {e}")
            _llm_instance = None
            raise


class GroqLLMManager:
    def __init__(self):
        self.client = AsyncGroq()
        self._api_key_verified = False

    def verify_api_key(self) -> bool:
        try:
            api_key = get_env_str("GROQ_API_KEY", "")
            if not api_key:
                raise ValueError("GROQ_API_KEY not found in environment.")
            self._api_key_verified = True
            return True
        except ValueError:
            self._api_key_verified = False
            return False

    def get_client(self) -> AsyncGroq:
        if not self._api_key_verified:
            if not self.verify_api_key():
                raise ValueError("GROQ_API_KEY not available.")
        return self.client
