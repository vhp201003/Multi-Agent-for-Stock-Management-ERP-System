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
from src.utils import get_shared_data

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
        agent_tasks = shared_data.get_tasks_for_agent(self.agent_type)
        if not agent_tasks:
            logger.warning(f"No tasks found for {self.agent_type}")
            return

        for task_node in agent_tasks:
            task_item = TaskQueueItem(
                query_id=data.query_id,
                sub_query=task_node.sub_query,
                task_id=task_node.task_id,
            )

            dependencies_satisfied = self._check_dependencies(task_node, shared_data)
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
            await self._update_pending_tasks(query_id)
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
                    agent_tasks = shared_data.get_tasks_for_agent(self.agent_type)
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

                task_node = next(
                    (
                        t
                        for t in shared_data.get_tasks_for_agent(self.agent_type)
                        if t.task_id == task_id
                    ),
                    None,
                )
                dependencies_satisfied = self._check_dependencies(
                    task_node, shared_data
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

    def _check_dependencies(self, task_node, shared_data: SharedData) -> bool:
        """Check if all dependencies for a task are completed using new SharedData schema."""
        if not task_node or not hasattr(task_node, "dependencies"):
            logger.warning(f"Invalid task_node provided: {task_node}")
            return False

        for dep_id in getattr(task_node, "dependencies", []):
            dep_exec = shared_data.tasks.get(dep_id)
            if (
                not dep_exec
                or dep_exec.status
                != shared_data.tasks[dep_id].status.__class__.COMPLETED
            ):
                return False
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

                    shared_data = await get_shared_data(self.redis, task.query_id)
                    conversation_id = (
                        shared_data.conversation_id if shared_data else None
                    )

                    channel = RedisChannels.get_command_channel(self.agent_type)
                    message = CommandMessage(
                        agent_type=self.agent_type,
                        command="execute",
                        query_id=task.query_id,
                        sub_query=task.sub_query,
                        conversation_id=conversation_id,
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
