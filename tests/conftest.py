"""Shared fixtures and utilities for all tests."""

import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx
import pytest_asyncio
import redis.asyncio as redis
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Re-export commonly used items for test modules
from src.typing.redis.constants import RedisKeys  # noqa: E402, F401

load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# Config (exported for test modules)
# =============================================================================

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8010")
REDIS_URL = (
    f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_client():
    """HTTP client for API requests."""
    client = httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0)
    yield client
    try:
        await client.aclose()
    except RuntimeError:
        pass


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def redis_client():
    """Redis client for state inspection."""
    client = redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    try:
        await client.aclose()
    except RuntimeError:
        pass


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def ensure_server_ready():
    """Wait for server to be ready before tests."""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=5.0) as client:
        for i in range(30):
            try:
                resp = await client.get("/")
                if resp.status_code in [200, 404]:
                    logger.info("✅ Server ready")
                    return
            except httpx.RequestError:
                await asyncio.sleep(1.0)
        raise RuntimeError(f"Server not ready at {API_BASE_URL}")
