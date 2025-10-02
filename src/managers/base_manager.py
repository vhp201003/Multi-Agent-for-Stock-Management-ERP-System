# src/managers/base_manager.py
import asyncio
import json
import logging
from datetime import datetime

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class BaseManager:
    def __init__(self, agent_name: str, redis_url: str = "redis://localhost:6379"):
        """Initialize the BaseManager with agent name and Redis connection.

        Args:
            agent_name (str): The name of the agent this manager handles.
            redis_url (str, optional): The URL for Redis connection. Defaults to "redis://localhost:6379".
        """
        self.agent_name = agent_name
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def listen_query_channel(self):
        """Listen for tasks from Orchestrator on agent:query_channel.

        Subscribes to the 'agent:query_channel' and processes incoming messages.
        If the message includes this agent's name, it extracts sub-queries and
        pushes them to the appropriate queue based on dependency checks.

        This method runs indefinitely until an error occurs or is cancelled.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("agent:query_channel")
        logger.info(f"Manager for {self.agent_name} listening on agent:query_channel")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if self.agent_name in data.get("agent_name", []):
                        query_id = data["query_id"]
                        sub_queries = data.get("sub_query", {}).get(self.agent_name, [])
                        # Check dependencies from shared data graph
                        shared_key = f"agent:shared_data:{query_id}"
                        graph = await self.redis.hget(shared_key, "graph")
                        dependencies_done = True  # Placeholder: implement DAG check
                        if graph:
                            # graph_data = json.loads(graph)  # Placeholder for DAG check
                            pass  # Implement DAG logic later
                        queue = (
                            "agent:queue"
                            if dependencies_done
                            else "agent:pending_queue"
                        )
                        for sub_query in sub_queries:
                            task = {"query_id": query_id, "query": sub_query}
                            await self.redis.lpush(
                                f"{queue}:{self.agent_name}", json.dumps(task)
                            )
                            logger.info(
                                f"Pushed task to {queue}:{self.agent_name}: {task}"
                            )
        except redis.RedisError as e:
            logger.error(f"Redis error in listen_query_channel: {e}")
        finally:
            await pubsub.unsubscribe("agent:query_channel")

    async def distribute_tasks(self):
        """Distribute tasks: move from pending to active if dependencies met, publish command.

        Continuously monitors the pending queue for tasks. If dependencies are satisfied,
        moves tasks to the active queue and publishes an execute command to the agent.

        This method runs in an infinite loop with a short sleep to avoid busy-waiting.
        """
        while True:
            # Check pending queue and move if ready
            pending_task = await self.redis.rpop(
                f"agent:pending_queue:{self.agent_name}"
            )
            if pending_task:
                task = json.loads(pending_task)
                query_id = task["query_id"]
                # Placeholder: check if dependencies done
                dependencies_done = True  # Implement DAG logic
                if dependencies_done:
                    await self.redis.lpush(
                        f"agent:queue:{self.agent_name}", json.dumps(task)
                    )
                    # Publish command to agent
                    await self.publish_command(query_id)
                    logger.info(f"Distributed task for {self.agent_name}: {task}")
            await asyncio.sleep(0.1)

    async def publish_command(self, query_id: str):
        """Publish execute command on agent:command_channel:{agent_name}.

        Publishes a message to the agent's command channel instructing it to execute
        the next task for the given query ID.

        Args:
            query_id (str): The unique identifier for the query.
        """
        channel = f"agent:command_channel:{self.agent_name}"
        message = {
            "agent_name": self.agent_name,
            "command": "execute",
            "query_id": query_id,
            "timestamp": datetime.now().isoformat(),
        }
        await self.redis.publish(channel, json.dumps(message))
        logger.info(f"Published command on {channel}: {message}")

    async def listen_task_updates(self):
        """Listen for task updates from Agent on agent:task_updates:{agent_name}.

        Subscribes to the agent's task update channel and processes incoming updates.
        Updates the shared data with results and context, validates using Pydantic,
        and triggers next tasks if dependencies are met.

        This method runs indefinitely until an error occurs or is cancelled.
        """
        pubsub = self.redis.pubsub()
        channel = f"agent:task_updates:{self.agent_name}"
        await pubsub.subscribe(channel)
        logger.info(f"Manager for {self.agent_name} listening on {channel}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    update = json.loads(message["data"])
                    query_id = update["query_id"]
                    # Update shared data as JSON
                    shared_key = f"agent:shared_data:{query_id}"
                    current_data = await self.redis.get(shared_key)
                    data = json.loads(current_data) if current_data else {}
                    # Update agents_done (append if list)
                    if "agents_done" not in data:
                        data["agents_done"] = []
                    if self.agent_name not in data["agents_done"]:
                        data["agents_done"].append(self.agent_name)
                    # Update results and context
                    if "results" not in data:
                        data["results"] = {}
                    data["results"][self.agent_name] = update["results"]
                    if "context" not in data:
                        data["context"] = {}
                    data["context"][self.agent_name] = update["context"]
                    # Validate with Pydantic
                    from src.typing.redis import SharedData

                    validated = SharedData(**data)
                    await self.redis.set(shared_key, validated.model_dump_json())
                    # Trigger next tasks if dependencies met
                    await self.check_and_trigger_next(query_id)
                    logger.info(f"Processed update for {query_id}: {update}")
        except redis.RedisError as e:
            logger.error(f"Redis error in listen_task_updates: {e}")
        finally:
            await pubsub.unsubscribe(channel)

    async def check_and_trigger_next(self, query_id: str):
        """Check DAG and trigger next dependent tasks.

        Analyzes the dependency graph for the given query ID and moves any
        pending tasks that have their dependencies satisfied to the active queue.

        Args:
            query_id (str): The unique identifier for the query.

        Note:
            Currently a placeholder. Implementation should traverse the DAG
            to identify and activate dependent tasks.
        """
        # Placeholder: Implement DAG traversal to move pending tasks
        pass

    async def start(self):
        """Start the BaseManager by running all listen methods concurrently."""
        await asyncio.gather(
            self.listen_query_channel(),
            self.distribute_tasks(),
            self.listen_task_updates(),
        )
