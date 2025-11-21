import logging
from typing import Optional

from qdrant_client import QdrantClient

from config.settings import get_qdrant_api_key, get_qdrant_host, get_qdrant_port, get_qdrant_url

logger = logging.getLogger(__name__)

_qdrant_instance: Optional["QdrantConnectionManager"] = None
_lock = __import__("threading").Lock()


def get_qdrant_connection() -> "QdrantConnectionManager":
    """Get singleton Qdrant connection."""
    global _qdrant_instance

    if _qdrant_instance is not None and _qdrant_instance.is_connected():
        return _qdrant_instance

    with _lock:
        if _qdrant_instance is not None and _qdrant_instance.is_connected():
            return _qdrant_instance
        try:
            _qdrant_instance = QdrantConnectionManager(
                host=get_qdrant_host(),
                port=get_qdrant_port(),
                url=get_qdrant_url(),
                api_key=get_qdrant_api_key(),
            )
            _qdrant_instance.connect()
            return _qdrant_instance

        except Exception as e:
            logger.error(f"Qdrant connection failed: {e}")
            _qdrant_instance = None
            raise


class QdrantConnectionManager:
    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 6333,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        prefer_grpc: bool = False,
    ):
        self.host = host or "localhost"
        self.port = port
        self.url = url
        self.api_key = api_key
        self.prefer_grpc = prefer_grpc

        self.client: Optional[QdrantClient] = None
        self._is_connected = False

    def connect(self) -> bool:
        try:
            if self.url:
                self.client = QdrantClient(
                    url=self.url,
                    api_key=self.api_key,
                    prefer_grpc=self.prefer_grpc,
                )
            else:
                self.client = QdrantClient(
                    host=self.host,
                    port=self.port,
                    api_key=self.api_key,
                    prefer_grpc=self.prefer_grpc,
                )

            if self.health_check():
                self._is_connected = True
                return True
            else:
                self._is_connected = False
                return False
        except Exception as e:
            self._is_connected = False
            logger.error(f"✗ Unexpected error during Qdrant connection: {e}")
            raise

    def disconnect(self) -> None:
        try:
            if self.client:
                self.client.close()
            self._is_connected = False
        except Exception as e:
            logger.error(f"Error during Qdrant disconnect: {e}")

    def health_check(self) -> bool:
        try:
            if self.client is None:
                return False
            self.client.get_collections()
            return True
        except Exception as e:
            logger.warning(f"Qdrant health check failed: {e}")
            return False

    def is_connected(self) -> bool:
        return self._is_connected and self.health_check()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass
