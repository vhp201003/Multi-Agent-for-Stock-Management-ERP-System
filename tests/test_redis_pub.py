import asyncio
import json
import uuid

import redis.asyncio as redis


async def publish_data(
    query: str, agent_name: str, redis_url: str = "redis://localhost:6379"
) -> str:
    """Publish query vào Redis channel agent_requests, trả về query_id."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    query_id = str(uuid.uuid4())
    message = json.dumps(
        {"query": query, "agent_name": agent_name, "query_id": query_id}
    )
    await redis_client.publish("agent_requests", message)
    print(f"Published query: {query}, ID: {query_id} to agent: {agent_name}")
    await redis_client.aclose()
    return query_id


async def main():
    while True:
        query = input("Enter query: ")
        agent_name = input("Enter agent name: ")
        await publish_data(query, agent_name)


if __name__ == "__main__":
    asyncio.run(main())
