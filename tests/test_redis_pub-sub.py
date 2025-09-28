import asyncio
import json
import uuid
import redis.asyncio as redis

async def publish_data(query: str, agent_name: str, redis_url: str = "redis://localhost:6379") -> str:
    """Publish query vào Redis channel agent_requests, trả về query_id."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    query_id = str(uuid.uuid4())
    message = json.dumps({"query": query, "agent_name": agent_name, "query_id": query_id})
    await redis_client.publish("agent_requests", message)
    print(f"Published query: {query}, ID: {query_id} to agent: {agent_name}")
    await redis_client.aclose()
    return query_id

async def subscribe_data(query_id: str, redis_url: str = "redis://localhost:6379", timeout: int = 10) -> dict:
    """Subscribe channel agent_requests, trả về message khi match query_id."""
    redis_client = redis.from_url(redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("agent_requests")
    
    try:
        async with asyncio.timeout(timeout):
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("query_id") == query_id:
                        print(f"Received message for query_id {query_id}: {data}")
                        return data
    except asyncio.TimeoutError:
        print(f"Timeout waiting for query_id {query_id}")
        return {"error": "Timeout"}
    finally:
        await pubsub.unsubscribe("agent_requests")
        await redis_client.aclose()

async def main():
    # Test publish và subscribe
    query = "Check stock for P001"
    agent_name = "inventory"
    query_id = str(uuid.uuid4())
    
    # Start subscribe task first to ensure it's listening
    task = asyncio.create_task(subscribe_data(query_id))
    await asyncio.sleep(0.1)  # Small delay to let subscribe start
    
    # Publish query
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
    message = json.dumps({"query": query, "agent_name": agent_name, "query_id": query_id})
    await redis_client.publish("agent_requests", message)
    print(f"Published query: {query}, ID: {query_id} to agent: {agent_name}")
    await redis_client.aclose()
    
    # Wait for subscribe result
    result = await task
    print(f"Final result: {result}")

if __name__ == "__main__":
    asyncio.run(main())