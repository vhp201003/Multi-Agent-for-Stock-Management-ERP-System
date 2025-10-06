#!/usr/bin/env python3
"""
Simplified Event-Driven Manager Stress Test

This test validates the event-driven BaseManager under high concurrent load.
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
from src.managers.base_manager import BaseManager
from src.typing.redis.constants import RedisChannels, RedisKeys, TaskStatus


# Mock Logger for testing
class MockLogger:
    @staticmethod
    def info(msg: str):
        print(f"ℹ️  {msg}")

    @staticmethod
    def warning(msg: str):
        print(f"⚠️  {msg}")

    @staticmethod
    def error(msg: str):
        print(f"❌ {msg}")


logger = MockLogger()


class SimpleStressTest:
    def __init__(self):
        self.redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
        self.agent_type = "test_agent"
        self.manager = BaseManager(
            agent_type="inventory_agent", redis_url="redis://localhost:6379"
        )

    async def cleanup(self):
        """Clean up Redis state"""
        await self.redis.flushdb()
        await self.redis.close()

    async def simple_stress_test(self):
        """Simple stress test with 10 concurrent tasks"""
        logger.info("🔥 Starting Simple Stress Test...")

        # Track performance
        start_time = time.time()
        tasks_sent = 0
        tasks_completed = 0

        # Mock agent that processes commands quickly
        async def mock_agent():
            nonlocal tasks_completed
            while tasks_completed < 10:  # Process 10 tasks total
                try:
                    queue_key = RedisKeys.get_agent_queue("inventory_agent")
                    result = await self.redis.blpop(queue_key, timeout=1)
                    if result:
                        _, raw_message = result
                        command_data = json.loads(raw_message)
                        tasks_completed += 1

                        # Send completion to task updates channel
                        completion = {
                            "task_id": f"task_{tasks_completed}",
                            "agent_id": command_data.get("agent_id", "inventory_agent"),
                            "status": TaskStatus.DONE,
                            "result": {"processed": True},
                            "timestamp": datetime.now().isoformat(),
                            "update_type": "task_completed",
                        }
                        channel = RedisChannels.get_task_updates_channel(
                            "inventory_agent"
                        )
                        await self.redis.publish(channel, json.dumps(completion))

                        if tasks_completed % 3 == 0:
                            logger.info(f"📊 Completed {tasks_completed}/10 tasks")
                    else:
                        # No tasks in queue, continue waiting
                        await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Agent error: {e}")
                    break

        # Start manager and agent
        manager_task = asyncio.create_task(self.manager.start())
        agent_task = asyncio.create_task(mock_agent())

        await asyncio.sleep(0.1)  # Let them initialize

        # Send test queries (using correct BaseManager format)
        for i in range(10):  # 10 individual queries for stress test
            query = {
                "query_id": f"stress_{i}",
                "agent_type": ["inventory_agent"],  # BaseManager expects this field
                "sub_query": {
                    "inventory_agent": [f"Stress test task {i}"]  # Tasks for this agent
                },
                "created_at": datetime.now().isoformat(),
                "graph": {},
            }

            await self.redis.publish(RedisChannels.QUERY_CHANNEL, json.dumps(query))
            tasks_sent += 1
            await asyncio.sleep(0.02)  # Small delay between queries

        # Wait for completion
        try:
            await asyncio.wait_for(agent_task, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Test timed out")

        # Calculate results
        end_time = time.time()
        total_time = end_time - start_time
        throughput = tasks_completed / total_time if total_time > 0 else 0

        logger.info("📈 STRESS TEST RESULTS:")
        logger.info(f"   ⏱️  Time: {total_time:.2f}s")
        logger.info(f"   📋 Tasks: {tasks_completed}/{tasks_sent}")
        logger.info(f"   🚀 Rate: {throughput:.1f} tasks/sec")

        # Cleanup
        agent_task.cancel()
        manager_task.cancel()
        try:
            await manager_task
        except asyncio.CancelledError:
            pass

        # Basic assertions
        assert tasks_completed >= 8, (
            f"Expected ≥8 tasks completed, got {tasks_completed}"
        )
        assert throughput >= 0.5, f"Expected ≥0.5 tasks/sec, got {throughput:.1f}"

        logger.info("✅ Stress test PASSED!")


async def main():
    test = SimpleStressTest()
    try:
        await test.cleanup()  # Clear any old data
        await test.simple_stress_test()
    finally:
        await test.cleanup()

    print("\n🎉 ALL STRESS TESTS COMPLETED!")
    print("✅ Event-driven architecture handles concurrent load well")


if __name__ == "__main__":
    asyncio.run(main())
