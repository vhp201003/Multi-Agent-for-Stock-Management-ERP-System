import logging
from typing import Optional

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_embedding_instance: Optional["EmbeddingManager"] = None
_lock = __import__("threading").Lock()


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
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = device
        self.model: Optional[SentenceTransformer] = None
        self._is_loaded = False

    def load_model(self) -> bool:
        try:
            if self.device:
                self.model = SentenceTransformer(self.model_name, device=self.device)
            else:
                self.model = SentenceTransformer(self.model_name)

            self._is_loaded = True
            return True

        except Exception as e:
            self._is_loaded = False
            logger.error(f"✗ Failed to load embedding model: {e}")
            raise RuntimeError(f"Cannot load model '{self.model_name}': {e}") from e

    def is_loaded(self) -> bool:
        return self._is_loaded and self.model is not None

    def embed(self, text: str, normalize: bool = True) -> list[float]:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        try:
            embedding = self.model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=normalize,
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error encoding text: {e}")
            raise

    def embed_query(self, query: str, normalize: bool = True) -> list[float]:
        return self.embed(query, normalize=normalize)

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
            embeddings = self.model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=normalize,
                show_progress_bar=show_progress,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error encoding batch: {e}")
            raise

    def get_dimension(self) -> int:
        if not self.is_loaded():
            raise RuntimeError("Model not loaded. Call load_model() first.")

        return self.model.get_sentence_embedding_dimension()

    def __del__(self):
        try:
            if self.model is not None:
                self._is_loaded = False
        except Exception:
            pass
