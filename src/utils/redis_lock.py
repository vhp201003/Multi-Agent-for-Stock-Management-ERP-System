"""Redis distributed lock implementation for critical sections."""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class RedisLockError(Exception):
    """Exception raised for Redis lock errors."""

    pass


class RedisLock:
    """Distributed lock using Redis with automatic expiry."""

    def __init__(
        self,
        redis_client,
        lock_key: str,
        timeout: float = 10.0,
        retry_delay: float = 0.1,
        max_retries: int = 50,
    ):
        """
        Initialize Redis lock.

        Args:
            redis_client: Redis async client
            lock_key: Unique key for the lock
            timeout: Lock auto-expiry timeout (seconds)
            retry_delay: Delay between lock acquisition retries (seconds)
            max_retries: Maximum number of acquisition retries
        """
        self.redis = redis_client
        self.lock_key = f"lock:{lock_key}"
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self.lock_value: Optional[str] = None

    async def acquire(self) -> bool:
        """
        Acquire the lock with retries.

        Returns:
            True if lock acquired, False otherwise
        """
        self.lock_value = str(uuid.uuid4())

        for attempt in range(self.max_retries):
            # SET NX EX: Set if Not eXists with EXpiry
            acquired = await self.redis.set(
                self.lock_key, self.lock_value, nx=True, ex=int(self.timeout)
            )

            if acquired:
                logger.debug(
                    f"Lock acquired: {self.lock_key} (attempt {attempt + 1}/{self.max_retries})"
                )
                return True

            # Lock already held, wait and retry
            await asyncio.sleep(self.retry_delay)

        logger.warning(
            f"Failed to acquire lock: {self.lock_key} after {self.max_retries} attempts"
        )
        return False

    async def release(self) -> bool:
        """
        Release the lock (only if we own it).

        Returns:
            True if lock released, False if we didn't own it
        """
        if not self.lock_value:
            return False

        # Lua script to atomically check value and delete
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        try:
            result = await self.redis.eval(lua_script, 1, self.lock_key, self.lock_value)
            released = bool(result)

            if released:
                logger.debug(f"Lock released: {self.lock_key}")
            else:
                logger.warning(
                    f"Lock release failed: {self.lock_key} (no longer owned or expired)"
                )

            return released

        except Exception as e:
            logger.error(f"Error releasing lock {self.lock_key}: {e}")
            return False
        finally:
            self.lock_value = None

    async def extend(self, additional_time: float = None) -> bool:
        """
        Extend lock expiry time.

        Args:
            additional_time: Additional seconds to extend (default: self.timeout)

        Returns:
            True if extended successfully
        """
        if not self.lock_value:
            return False

        extend_time = additional_time or self.timeout

        # Lua script to atomically check value and extend
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """

        try:
            result = await self.redis.eval(
                lua_script, 1, self.lock_key, self.lock_value, int(extend_time)
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Error extending lock {self.lock_key}: {e}")
            return False

    async def is_locked(self) -> bool:
        """Check if lock exists (by any holder)."""
        return await self.redis.exists(self.lock_key) > 0

    async def is_owned(self) -> bool:
        """Check if we own the lock."""
        if not self.lock_value:
            return False
        current_value = await self.redis.get(self.lock_key)
        return current_value == self.lock_value


@asynccontextmanager
async def redis_lock(
    redis_client,
    lock_key: str,
    timeout: float = 10.0,
    retry_delay: float = 0.1,
    max_retries: int = 50,
    raise_on_failure: bool = True,
):
    """
    Context manager for Redis distributed lock.

    Usage:
        async with redis_lock(redis, "my_critical_section"):
            # Critical section code
            pass

    Args:
        redis_client: Redis async client
        lock_key: Unique key for the lock
        timeout: Lock auto-expiry timeout (seconds)
        retry_delay: Delay between retries (seconds)
        max_retries: Maximum acquisition attempts
        raise_on_failure: Raise exception if lock acquisition fails

    Raises:
        RedisLockError: If lock acquisition fails and raise_on_failure=True
    """
    lock = RedisLock(redis_client, lock_key, timeout, retry_delay, max_retries)

    acquired = await lock.acquire()
    if not acquired:
        if raise_on_failure:
            raise RedisLockError(f"Failed to acquire lock: {lock_key}")
        logger.warning(f"Proceeding without lock: {lock_key}")

    try:
        yield lock
    finally:
        if acquired:
            await lock.release()
