import asyncio
from typing import Callable, Dict

import redis.asyncio as redis

# Define handlers as async funcs
async def handle_query_channel(message: str):
    print(f"Processing query: {message}")
    # Add logic: parse JSON, trigger orchestration

async def handle_task_updates(message: str):
    print(f"Updating task: {message}")
    # Add logic: update shared data

async def handle_default(message: str, channel: str):
    print(f"Default action for {channel}: {message}")

# Dict mapping channels to handlers
CHANNEL_HANDLERS: Dict[str, Callable[[str], None]] = {
    "agent:query_channel": handle_query_channel,
    "agent:task_updates": handle_task_updates,
    # Add more as needed
}

async def subscribe_channels(channels: list, redis_url: str = "redis://localhost:6379"):
    redis_client = redis.from_url(redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(*channels)

    print(f"Subscribed to channels: {channels}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"]
                data = message["data"]
                handler = CHANNEL_HANDLERS.get(channel, lambda msg: handle_default(msg, channel))
                await handler(data)
    except KeyboardInterrupt:
        print("Stopping subscriber...")
    finally:
        await pubsub.unsubscribe(*channels)
        await redis_client.aclose()

async def main():
    channels_input = input("Enter channels (comma-separated): ")
    channels = [ch.strip() for ch in channels_input.split(",") if ch.strip()]
    if channels:
        await subscribe_channels(channels)
    else:
        print("No channels provided.")

if __name__ == "__main__":
    asyncio.run(main())
