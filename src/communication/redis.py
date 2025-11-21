import logging
from typing import Optional

import redis.asyncio as aioredis

from config.settings import get_redis_host, get_redis_port

logger = logging.getLogger(__name__)

_async_redis_instance: Optional["AsyncRedisConnectionManager"] = None
_lock = __import__("threading").Lock()


def get_async_redis_connection() -> "AsyncRedisConnectionManager":
    """Get singleton async Redis connection for entire system."""
    global _async_redis_instance

    if _async_redis_instance is not None:
        return _async_redis_instance

    with _lock:
        if _async_redis_instance is not None:
            return _async_redis_instance
        try:
            _async_redis_instance = AsyncRedisConnectionManager(
                host=get_redis_host(),
                port=get_redis_port(),
            )
            return _async_redis_instance

        except Exception as e:
            logger.error(f"Async Redis connection failed: {e}")
            _async_redis_instance = None
            raise


# Alias for backward compatibility
get_redis_connection = get_async_redis_connection


class AsyncRedisConnectionManager:
    """Async Redis connection manager for entire system."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        decode_responses: bool = True,
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.decode_responses = decode_responses
        self._client: Optional[aioredis.Redis] = None

    @property
    def client(self) -> aioredis.Redis:
        """Get or create async Redis client (lazy initialization)."""
        if self._client is None:
            self._client = aioredis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=self.decode_responses,
            )
        return self._client

    async def ping(self) -> bool:
        """Check if Redis is reachable."""
        try:
            return await self.client.ping()
        except Exception as e:
            logger.warning(f"Async Redis ping failed: {e}")
            return False

    async def close(self) -> None:
        """Close the async Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
