# src/managers/base_manager.py
import asyncio
import json

import redis.asyncio as redis
from config.settings import QUERY_CHANNEL, REDIS_URL, RESULT_CHANNEL_TEMPLATE


class BaseManager:
    def __init__(self, agent_name: str, redis_url: str = REDIS_URL):
        self.agent_name = agent_name
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def listen_channel(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(QUERY_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                if data.get("agent_name") == self.agent_name:
                    await self.redis.lpush(
                        f"manager_queue:{self.agent_name}", json.dumps(data)
                    )

    async def distribute_to_agent(self):
        while True:
            message = await self.redis.rpop(f"manager_queue:{self.agent_name}")
            if message:
                data = json.loads(message)
                await self.redis.lpush(
                    f"agent_requests:{self.agent_name}", json.dumps(data)
                )
            await asyncio.sleep(0.1)

    async def listen_result(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(
            RESULT_CHANNEL_TEMPLATE.format(agent_name=self.agent_name)
        )
        async for message in pubsub.listen():
            if message["type"] == "message":
                result = json.loads(message["data"])
                query_id = result["query_id"]
                await self.redis.hset(
                    f"agent_result:{query_id}:{self.agent_name}", mapping=result
                )
                await self.redis.publish("agent_results", json.dumps(result))
