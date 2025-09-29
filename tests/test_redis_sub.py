import asyncio
import json

import redis.asyncio as redis


async def subscribe_all(redis_url: str = "redis://localhost:6379"):
    """Subscribe channel agent_requests và in tất cả messages."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("agent_requests")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                print(f"Received message: {data}")
    except KeyboardInterrupt:
        print("Stopping subscriber...")
    finally:
        await pubsub.unsubscribe("agent_requests")
        await redis_client.aclose()


async def main():
    await subscribe_all()


if __name__ == "__main__":
    asyncio.run(main())
