import json
import logging
from datetime import datetime

import redis.asyncio as redis
from src.typing.redis import (
    AgentStatus,
    CommandMessage,
    QueryTask,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskQueueItem,
    TaskUpdate,
)
from src.typing.redis.shared_data import TaskGraphUtils

logger = logging.getLogger(__name__)


class BaseManager:
    def __init__(self, agent_type: str, redis_url: str = "redis://localhost:6379"):
        self.agent_type = agent_type
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def get_pub_channels(self) -> list[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def get_sub_channels(self) -> list[str]:
        return [RedisChannels.QUERY_CHANNEL, RedisChannels.TASK_UPDATES]

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self._handle_message(message["channel"], message["data"])
        except redis.RedisError as e:
            logger.error(f"Redis connection error: {e}")
            raise
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_message(self, channel: str, raw_data: str):
        try:
            data = json.loads(raw_data)

            if channel == RedisChannels.QUERY_CHANNEL:
                await self._process_query_message(QueryTask(**data))
            elif channel == RedisChannels.TASK_UPDATES:
                await self._process_task_update(TaskUpdate(**data))

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in channel {channel}: {e}")
        except Exception as e:
            logger.error(f"Message processing error in {self.agent_type}: {e}")

    async def _process_query_message(self, data: QueryTask):
        if self.agent_type not in data.agents_needed:
            return

        shared_key = RedisKeys.get_shared_data_key(data.query_id)
        shared_data_raw = await self.redis.json().get(shared_key)
        if not shared_data_raw:
            logger.error(f"No shared data found for query {data.query_id}")
            return

        shared_data = SharedData(**shared_data_raw)
        agent_tasks = TaskGraphUtils.get_tasks_for_agent(
            shared_data.task_graph, self.agent_type
        )
        if not agent_tasks:
            logger.warning(f"No tasks found for {self.agent_type}")
            return

        for task_node in agent_tasks:
            task_item = TaskQueueItem(
                query_id=data.query_id,
                sub_query=task_node.sub_query,
                task_id=task_node.task_id,
            )

            dependencies_satisfied = await self._check_dependencies(
                task_node.task_id, shared_data, data.query_id
            )
            queue_key = (
                RedisKeys.get_agent_queue(self.agent_type)
                if dependencies_satisfied
                else RedisKeys.get_agent_pending_queue(self.agent_type)
            )

            await self.redis.rpush(queue_key, task_item.model_dump_json())

        await self._execute_next_available_task()

    async def _process_task_update(self, task_update: TaskUpdate):
        query_id = task_update.query_id
        if not query_id:
            logger.error("Missing query_id in task update")
            return

        if not task_update.agent_type or not isinstance(task_update.agent_type, str):
            logger.error(f"Invalid agent_type in task update: {task_update.agent_type}")
            return

        if task_update.agent_type == self.agent_type:
            await self._execute_next_available_task()
        elif task_update.agent_type != "chat_agent":  # ChatAgent is final
            await self._update_pending_tasks(query_id)

    async def _update_pending_tasks(self, query_id: str):
        try:
            pending_queue_key = RedisKeys.get_agent_pending_queue(self.agent_type)
            active_queue_key = RedisKeys.get_agent_queue(self.agent_type)

            pending_tasks_raw = await self.redis.lrange(pending_queue_key, 0, -1)
            if not pending_tasks_raw:
                return

            shared_data_raw = await self.redis.json().get(
                RedisKeys.get_shared_data_key(query_id)
            )
            if not shared_data_raw:
                logger.warning(f"No shared data for query {query_id}")
                return

            shared_data = SharedData(**shared_data_raw)
            ready_tasks = []
            still_pending = []

            for task_raw in pending_tasks_raw:
                task = TaskQueueItem(**json.loads(task_raw))

                if task.query_id != query_id:
                    still_pending.append(task_raw)
                    continue

                task_id = getattr(task, "task_id", None)
                if not task_id:
                    agent_tasks = TaskGraphUtils.get_tasks_for_agent(
                        shared_data.task_graph, self.agent_type
                    )
                    for t in agent_tasks:
                        if t.sub_query == task.sub_query:
                            task_id = t.task_id
                            break

                if not task_id:
                    logger.warning(
                        f"Could not find task_id for sub_query: {task.sub_query}"
                    )
                    still_pending.append(task_raw)
                    continue

                dependencies_satisfied = await self._check_dependencies(
                    task_id, shared_data, query_id
                )
                if dependencies_satisfied:
                    ready_tasks.append(task_raw)
                    logger.info(
                        f"Task {task_id} dependencies satisfied, moving to active"
                    )
                else:
                    still_pending.append(task_raw)

            if ready_tasks:
                pipeline = self.redis.pipeline()
                pipeline.delete(pending_queue_key)
                if still_pending:
                    pipeline.rpush(pending_queue_key, *still_pending)
                pipeline.rpush(active_queue_key, *ready_tasks)
                await pipeline.execute()

                logger.info(
                    f"Moved {len(ready_tasks)} tasks to active, {len(still_pending)} remain pending"
                )
                await self._execute_next_available_task()

        except Exception as e:
            logger.error(f"Failed to update pending tasks for {self.agent_type}: {e}")

    async def _check_dependencies(
        self, task_id: str, shared_data: SharedData, query_id: str
    ) -> bool:
        if not task_id or not isinstance(task_id, str):
            logger.warning(f"Invalid task_id provided: {task_id}")
            return False

        if not shared_data or not shared_data.task_graph:
            return True

        try:
            completed_ids = set()
            for agent_type, agent_results in shared_data.results.items():
                if agent_type in shared_data.task_graph.nodes:
                    for task in shared_data.task_graph.nodes[agent_type]:
                        if task.sub_query in agent_results:
                            completed_ids.add(task.task_id)

            task_node = TaskGraphUtils.get_task_by_id(shared_data.task_graph, task_id)
            if not task_node:
                logger.warning(f"Task {task_id} not found in task graph")
                return True

            return all(dep_id in completed_ids for dep_id in task_node.dependencies)

        except Exception as e:
            logger.error(f"Dependency check failed for {task_id}: {e}")
            return True

    async def _execute_next_available_task(self):
        try:
            status_value = await self.redis.hget(
                RedisKeys.AGENT_STATUS, self.agent_type
            )
            agent_status = (
                AgentStatus(status_value) if status_value else AgentStatus.IDLE
            )

            if agent_status == AgentStatus.ERROR:
                await self.redis.hset(
                    RedisKeys.AGENT_STATUS, self.agent_type, AgentStatus.IDLE.value
                )
                agent_status = AgentStatus.IDLE

            if agent_status == AgentStatus.IDLE:
                task_data = await self.redis.lpop(
                    RedisKeys.get_agent_queue(self.agent_type)
                )
                if task_data:
                    task = TaskQueueItem(**json.loads(task_data))

                    channel = RedisChannels.get_command_channel(self.agent_type)
                    message = CommandMessage(
                        agent_type=self.agent_type,
                        command="execute",
                        query_id=task.query_id,
                        sub_query=task.sub_query,
                        timestamp=datetime.now().isoformat(),
                    )
                    await self.redis.publish(channel, json.dumps(message.model_dump()))
                    logger.info(
                        f"Executing task on {self.agent_type}: {task.sub_query}"
                    )

        except Exception as e:
            logger.error(f"Failed to execute next task for {self.agent_type}: {e}")

    async def start(self):
        await self.listen_channels()
