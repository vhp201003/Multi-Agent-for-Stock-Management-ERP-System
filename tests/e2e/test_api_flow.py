"""
Performance Tests: API Query Flow
==================================

Tests:
1. test_sequential_queries - Run all queries one by one
2. test_concurrent_queries - Run 5 random queries in parallel (simulate multiple users)
"""

import asyncio
import json
import logging
import os
import random
import time
import uuid
from pathlib import Path

import httpx
import pytest
import redis.asyncio as redis

from tests.conftest import REDIS_URL, RedisKeys

logger = logging.getLogger(__name__)

# Load test cases
TEST_CASES = json.loads((Path(__file__).parent / "test_config.json").read_text())

# Config
CONCURRENT_USERS = 3  # Reduced for debugging
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8010")


# =============================================================================
# Helpers
# =============================================================================


async def send_query(api_client, query_id: str, query: str, user_id: str = "test_user"):
    """Send a query to the API."""
    return await api_client.post(
        "/query",
        json={"query_id": query_id, "query": query, "user_id": user_id},
        timeout=120.0,  # Increased timeout
    )
    


async def wait_for_redis_status(redis_client, query_id: str, start_time: float, timeout: int = 120):
    """
    Poll Redis until query completes.
    Returns: (status, elapsed_seconds)
    """
    key = RedisKeys.get_shared_data_key(query_id)

    for _ in range(timeout):
        data = await redis_client.json().get(key)
        if data:
            status = data.get("status", "")
            if status in ["completed", "done"]:
                return "success", time.perf_counter() - start_time
            if status in ["error", "failed"]:
                return "failed", time.perf_counter() - start_time
        await asyncio.sleep(1.0)

    return "timeout", time.perf_counter() - start_time


async def run_single_query(api_client, redis_client, query: str, user_id: str):
    """
    Execute a single query end-to-end.
    Returns: dict with query_id, status, elapsed time
    """
    query_id = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    key = RedisKeys.get_shared_data_key(query_id)

    # Clean old data
    await redis_client.delete(key)

    # Start timer BEFORE sending query
    start = time.perf_counter()

    # Send query
    resp = await send_query(api_client, query_id, query, user_id)

    if resp.status_code not in [200, 202]:
        return {
            "query_id": query_id,
            "query": query,
            "user_id": user_id,
            "status": "error",
            "elapsed": time.perf_counter() - start,
            "error": f"HTTP {resp.status_code}",
        }

    # Wait for completion (pass start_time for accurate timing)
    status, elapsed = await wait_for_redis_status(redis_client, query_id, start)

    return {
        "query_id": query_id,
        "query": query,
        "user_id": user_id,
        "status": status,
        "elapsed": elapsed,
    }


async def run_single_query_isolated(query: str, user_id: str):
    """
    Execute a single query with its own clients (for concurrent testing).
    Each task gets its own HTTP and Redis clients to avoid conflicts.
    """
    query_id = f"TEST_{uuid.uuid4().hex[:8].upper()}"
    key = RedisKeys.get_shared_data_key(query_id)

    # Create isolated clients for this task
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=120.0) as http_client:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            # Clean old data
            await redis_client.delete(key)

            # Start timer
            start = time.perf_counter()

            # Send query
            resp = await http_client.post(
                "/query",
                json={"query_id": query_id, "query": query, "user_id": user_id},
            )

            if resp.status_code not in [200, 202]:
                return {
                    "query_id": query_id,
                    "query": query,
                    "user_id": user_id,
                    "status": "error",
                    "elapsed": time.perf_counter() - start,
                    "error": f"HTTP {resp.status_code}",
                }

            # Wait for completion
            status, elapsed = await wait_for_redis_status(redis_client, query_id, start)

            return {
                "query_id": query_id,
                "query": query,
                "user_id": user_id,
                "status": status,
                "elapsed": elapsed,
            }
        finally:
            await redis_client.aclose()


def print_results(results: list[dict], title: str):
    """Print test results summary."""
    passed = sum(1 for r in results if r["status"] == "success")
    total_time = sum(r["elapsed"] for r in results)
    avg_time = total_time / len(results) if results else 0

    logger.info(f"\n{'=' * 60}")
    logger.info(f"📊 {title}")
    logger.info(f"{'=' * 60}")
    logger.info(f"   ✅ Passed: {passed}/{len(results)}")
    logger.info(f"   ⏱️  Total Time: {total_time:.2f}s")
    logger.info(f"   ⏱️  Avg Time: {avg_time:.2f}s")

    if len(results) > 1:
        min_time = min(r["elapsed"] for r in results)
        max_time = max(r["elapsed"] for r in results)
        logger.info(f"   ⏱️  Min/Max: {min_time:.2f}s / {max_time:.2f}s")

    logger.info(f"{'=' * 60}")

    # Detail per query
    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        logger.info(f"   {icon} [{r['user_id']}] {r['query'][:40]}... → {r['elapsed']:.2f}s")


# =============================================================================
# Test Cases
# =============================================================================


@pytest.mark.asyncio
async def test_sequential_queries(api_client, redis_client):
    """
    Test 1: Sequential Query Processing
    ------------------------------------
    Run all queries one by one, measure individual times.
    Simulates: Single user making multiple requests.
    """
    logger.info("\n" + "=" * 60)
    logger.info("🔄 TEST: Sequential Queries")
    logger.info("=" * 60)

    results = []

    for i, case in enumerate(TEST_CASES, 1):
        query = case["query"]
        logger.info(f"\n[{i}/{len(TEST_CASES)}] Sending: {query}")

        result = await run_single_query(
            api_client,
            redis_client,
            query,
            user_id=f"seq_user_{i}",
        )

        icon = "✅" if result["status"] == "success" else "❌"
        logger.info(f"    → {icon} {result['status']} in {result['elapsed']:.2f}s")

        results.append(result)

    print_results(results, "SEQUENTIAL TEST RESULTS")

    assert all(r["status"] == "success" for r in results), "Some sequential queries failed"


@pytest.mark.asyncio
async def test_concurrent_queries():
    """
    Test 2: Concurrent Query Processing
    ------------------------------------
    Run N random queries in parallel.
    Simulates: Multiple users querying at the same time.

    Note: Uses isolated clients per task to avoid Redis connection conflicts.
    """
    logger.info("\n" + "=" * 60)
    logger.info(f"⚡ TEST: Concurrent Queries ({CONCURRENT_USERS} users)")
    logger.info("=" * 60)

    # Random select queries (with replacement if needed)
    selected_queries = random.choices(TEST_CASES, k=CONCURRENT_USERS)

    logger.info(f"\nSelected {len(selected_queries)} queries:")
    for i, case in enumerate(selected_queries, 1):
        logger.info(f"   [{i}] {case['query'][:50]}...")

    # Create concurrent tasks with isolated clients
    logger.info("\n🚀 Launching all queries concurrently...")
    start_total = time.perf_counter()

    tasks = [
        run_single_query_isolated(
            case["query"],
            user_id=f"concurrent_user_{i}",
        )
        for i, case in enumerate(selected_queries, 1)
    ]

    # Wait for all to complete
    results = await asyncio.gather(*tasks)
    total_elapsed = time.perf_counter() - start_total

    # Print results
    print_results(list(results), "CONCURRENT TEST RESULTS")
    logger.info(f"   🏁 Wall-clock time: {total_elapsed:.2f}s")

    # Calculate throughput
    if total_elapsed > 0:
        throughput = len(results) / total_elapsed
        logger.info(f"   📈 Throughput: {throughput:.2f} queries/sec")

    assert all(r["status"] == "success" for r in results), "Some concurrent queries failed"
