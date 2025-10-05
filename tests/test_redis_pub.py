import asyncio

import redis.asyncio as redis


async def publish_message(
    channel: str, message: str, redis_url: str = "redis://localhost:6379"
):
    """Publish message vào Redis channel tùy ý."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    await redis_client.publish(channel, message)
    print(f"Published to channel '{channel}': {message}")
    await redis_client.aclose()


async def main():
    while True:
        channel = input("Enter channel: ")
        message = input("Enter message: ")
        if channel and message:
            await publish_message(channel, message)
        else:
            print("Channel and message cannot be empty.")


if __name__ == "__main__":
    asyncio.run(main())
