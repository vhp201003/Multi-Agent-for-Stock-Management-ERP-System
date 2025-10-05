#!/usr/bin/env python3
"""
Basic Event-Driven Manager Test

Simple test to verify manager puts tasks in queue and responds to events.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging

import redis.asyncio as redis
from src.managers.base_manager import BaseManager
from src.typing.redis.constants import RedisChannels, RedisKeys

# Enable logging to see what BaseManager is doing
logging.basicConfig(level=logging.INFO)


class BasicManagerTest:
    def __init__(self):
        self.redis = redis.from_url("redis://localhost:6379", decode_responses=True)
        self.manager = BaseManager(agent_type="inventory_agent")

    async def cleanup(self):
        """Clean up Redis state"""
        await self.redis.flushall()
        await self.redis.aclose()

    async def basic_test(self):
        """Basic test - send query and check if task appears in queue"""
        print("🧪 Basic Manager Test - Check Task Queue")

        # Start manager in background
        print("🚀 Starting BaseManager...")
        manager_task = asyncio.create_task(self.manager.start())
        await asyncio.sleep(0.5)  # Let manager start and subscribe
        print("✅ Manager started")

        # Check initial queue state
        queue_key = RedisKeys.get_agent_queue("inventory_agent")
        initial_count = await self.redis.llen(queue_key)
        print(f"📊 Initial queue length: {initial_count}")

        # Send a simple query (using format expected by BaseManager)
        query_data = {
            "query_id": "test_query_001",
            "agent_type": ["inventory_agent"],  # BaseManager expects this field
            "sub_query": {
                "inventory_agent": ["Simple test task"]  # Tasks for this agent
            },
            "created_at": datetime.now().isoformat(),
            "graph": {},
        }

        print("📤 Sending query via QUERY_CHANNEL...")
        await self.redis.publish(RedisChannels.QUERY_CHANNEL, json.dumps(query_data))

        # Give some time for processing
        print("⏳ Waiting for manager to process query...")
        await asyncio.sleep(2.0)  # Give more time

        # Check queue after query
        final_count = await self.redis.llen(queue_key)
        print(f"📊 Final queue length: {final_count}")

        # Check if there's actually something in the queue
        if final_count > 0:
            task_data = await self.redis.lindex(queue_key, 0)
            print(f"📋 Task in queue: {task_data}")

        # Check shared data
        shared_key = RedisKeys.get_shared_data_key("test_query_001")
        shared_data = await self.redis.get(shared_key)
        print(f"🗃️  Shared data exists: {shared_data is not None}")
        if shared_data:
            print(f"🗃️  Shared data: {shared_data[:200]}...")

        # Cleanup
        manager_task.cancel()
        try:
            await manager_task
        except asyncio.CancelledError:
            pass

        # Results
        tasks_added = final_count - initial_count
        print("\n✅ Test Results:")
        print(f"   📈 Tasks added to queue: {tasks_added}")
        print(f"   🗃️  Shared data created: {'Yes' if shared_data else 'No'}")

        if tasks_added > 0:
            print("🎉 SUCCESS: Manager is adding tasks to queue!")
            return True
        else:
            print("❌ FAILED: Manager not adding tasks to queue")
            return False


async def main():
    test = BasicManagerTest()
    try:
        await test.cleanup()
        success = await test.basic_test()
        if success:
            print("\n🏆 Basic event-driven architecture is working!")
        else:
            print("\n💥 Event-driven architecture has issues")
    finally:
        await test.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
