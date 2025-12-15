import logging
import os
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

_embedding_instance: Optional["EmbeddingManager"] = None
_lock = __import__("threading").Lock()

DEFAULT_DIMENSION = 768  # Dimension for 'models/text-embedding-004'


def get_embedding_model() -> "EmbeddingManager":
    global _embedding_instance

    if _embedding_instance is not None:
        return _embedding_instance

    with _lock:
        if _embedding_instance is not None:
            return _embedding_instance
        try:
            _embedding_instance = EmbeddingManager()
            _embedding_instance.load_model()
            return _embedding_instance

        except Exception as e:
            logger.error(f"✗ Embedding model initialization failed: {e}")
            _embedding_instance = None  # Reset for retry
            raise


class EmbeddingManager:
    def __init__(
        self,
        model_name: str = "models/text-embedding-004",
        api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._is_loaded = False
        self._dimension = DEFAULT_DIMENSION

    def load_model(self) -> bool:
        try:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables")

            genai.configure(api_key=self.api_key)
            self._is_loaded = True
            logger.info(
                f"✓ Gemini embedding model '{self.model_name}' configured successfully"
            )
            return True

        except Exception as e:
            self._is_loaded = False
            logger.error(f"✗ Failed to configure Gemini embedding model: {e}")
            raise RuntimeError(
                f"Cannot configure Gemini model '{self.model_name}': {e}"
            ) from e

    def is_loaded(self) -> bool:
        return self._is_loaded

    def embed(self, text: str, normalize: bool = True) -> list[float]:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        try:
            result = genai.embed_content(
                model=self.model_name,
                content=text,
                task_type="retrieval_document",
            )
            return result["embedding"]
        except Exception as e:
            logger.error(f"Error encoding text: {e}")
            raise

    def embed_query(self, query: str, normalize: bool = True) -> list[float]:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        try:
            result = genai.embed_content(
                model=self.model_name,
                content=query,
                task_type="retrieval_query",
            )
            return result["embedding"]
        except Exception as e:
            logger.error(f"Error encoding query: {e}")
            raise

    def embed_batch(
        self,
        texts: list[str],
        normalize: bool = True,
        show_progress: bool = False,
    ) -> list[list[float]]:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        if not texts:
            return []

        try:
            embeddings = []
            for text in texts:
                result = genai.embed_content(
                    model=self.model_name,
                    content=text,
                    task_type="retrieval_document",
                )
                embeddings.append(result["embedding"])
            return embeddings
        except Exception as e:
            logger.error(f"Error encoding batch: {e}")
            raise

    def get_dimension(self) -> int:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        return self._dimension

    def __del__(self):
        try:
            self._is_loaded = False
        except Exception:
            pass
