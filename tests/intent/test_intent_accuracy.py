import asyncio
import json
import logging
import uuid
from pathlib import Path

import httpx
import pytest
import redis.asyncio as redis

from tests.conftest import REDIS_URL, RedisKeys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8010"

BASIC_CONFIG_PATH = Path(__file__).parent / "intent_config.json"
COMPLEX_CONFIG_PATH = Path(__file__).parent / "complex_intent_config.json"


def load_test_cases(path: Path):
    with open(path, "r") as f:
        return json.load(f)


async def wait_for_data_populated(redis_client, query_id: str, timeout: int = 15):
    """
    Wait until shared data is created and populated with agents_needed.
    """
    key = RedisKeys.get_shared_data_key(query_id)
    for _ in range(timeout * 2):  # Check every 0.5s
        data = await redis_client.json().get(key)
        if data and "agents_needed" in data:
            return data
        await asyncio.sleep(0.5)
    return None


async def run_intent_test_suite(config_path: Path, suite_name: str):
    test_cases = load_test_cases(config_path)
    results = []

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=45.0) as http_client:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            for case in test_cases:
                query = case["query"]
                expected = set(case.get("expected_agents", []))
                query_id = f"INTENT_{uuid.uuid4().hex[:8].upper()}"

                logger.info(f"[{suite_name}] Testing: {query[:60]}...")

                # Send query
                resp = await http_client.post(
                    "/query",
                    json={
                        "query_id": query_id,
                        "query": query,
                        "user_id": "test_intent",
                    },
                )
                assert resp.status_code in [200, 202], (
                    f"API request failed: {resp.text}"
                )

                # Poll Redis for decision
                data = await wait_for_data_populated(redis_client, query_id)

                if not data:
                    logger.error(f"❌ Timeout waiting for orchestration: {query}")
                    results.append((query, expected, "TIMEOUT", False))
                    continue

                actual = set(data.get("agents_needed", []))

                # Check match logic:
                # For complex queries, we expect ALL listed agents to be present in 'actual'.
                # 'actual' might contain MORE agents (e.g. 'chat'), which is fine.
                # So we check if EXPECTED is a SUBSET of ACTUAL.
                is_match = expected.issubset(actual)

                status = "✅ MATCH" if is_match else f"❌ MISMATCH (Got: {actual})"
                logger.info(f"   expected: {expected} | actual: {actual} -> {status}")

                results.append((query, expected, actual, is_match))

        finally:
            await redis_client.aclose()

    return results


def log_summary(results, suite_name):
    logger.info(f"\n{'=' * 60}\n📊 {suite_name} SUMMARY\n{'=' * 60}")
    failed_count = 0
    for query, expected, actual, passed in results:
        icon = "✅" if passed else "❌"
        actual_str = (
            str(actual) if isinstance(actual, (set, list, dict)) else str(actual)
        )

        logger.info(f"{icon} Query: {query[:60]}...")
        logger.info(f"   Expected (subset): {expected}")
        logger.info(f"   Actual:            {actual_str}")
        logger.info("-" * 60)

        if not passed:
            failed_count += 1
    return failed_count


@pytest.mark.asyncio
async def test_intent_accuracy():
    """Test basic single-agent intents."""
    results = await run_intent_test_suite(BASIC_CONFIG_PATH, "BASIC INTENTS")
    failures = log_summary(results, "BASIC INTENTS")
    assert failures == 0, f"Failed {failures} basic intent tests"


@pytest.mark.asyncio
async def test_complex_intent_accuracy():
    """Test complex multi-agent intents."""
    results = await run_intent_test_suite(COMPLEX_CONFIG_PATH, "COMPLEX INTENTS")
    failures = log_summary(results, "COMPLEX INTENTS")
    assert failures == 0, f"Failed {failures} complex intent tests"
