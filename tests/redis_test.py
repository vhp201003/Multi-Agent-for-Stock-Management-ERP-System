#!/usr/bin/env python3
"""
Redis PubSub Basic Test

Test Redis pub/sub functionality directly
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
from src.typing.redis.constants import RedisChannels


async def test_pubsub():
    """Test basic Redis pub/sub functionality"""
    print("🧪 Testing Redis Pub/Sub...")

    r = redis.from_url("redis://localhost:6379", decode_responses=True)

    # Test message received
    message_received = False

    async def subscriber():
        nonlocal message_received
        pubsub = r.pubsub()
        await pubsub.subscribe(RedisChannels.QUERY_CHANNEL)
        print(f"📡 Subscribed to {RedisChannels.QUERY_CHANNEL}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    print(f"📨 Received message: {message['data'][:100]}...")
                    message_received = True
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(RedisChannels.QUERY_CHANNEL)

    # Start subscriber
    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.1)  # Let subscriber start

    # Send test message
    test_data = {"query_id": "test_001", "message": "Hello Redis PubSub!"}

    print(f"📤 Publishing to {RedisChannels.QUERY_CHANNEL}...")
    await r.publish(RedisChannels.QUERY_CHANNEL, json.dumps(test_data))

    # Wait a bit for message
    await asyncio.sleep(0.5)

    # Cancel subscriber
    sub_task.cancel()
    try:
        await sub_task
    except asyncio.CancelledError:
        pass

    await r.aclose()

    if message_received:
        print("✅ Redis Pub/Sub is working!")
        return True
    else:
        print("❌ Redis Pub/Sub failed!")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_pubsub())
    if not success:
        print("💥 Redis connection issues - check if Redis server is running")
        exit(1)
    print("🏆 Redis is working properly!")
