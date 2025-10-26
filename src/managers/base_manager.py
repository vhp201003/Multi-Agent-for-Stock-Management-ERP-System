import json
import logging

import redis.asyncio as redis
from src.agents.chat_agent import AGENT_TYPE as CHAT_AGENT_TYPE
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

    async def get_sub_channels(self) -> list[str]:
        return [RedisChannels.QUERY_CHANNEL, RedisChannels.TASK_UPDATES]

    async def listen_channels(self):
        while True:
            pubsub = self.redis.pubsub()
            channels = await self.get_sub_channels()
            await pubsub.subscribe(*channels)

            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        channel = message["channel"]
                        if channel == RedisChannels.QUERY_CHANNEL:
                            await self._process_query_message(
                                QueryTask.model_validate_json(message["data"])
                            )
                        elif channel == RedisChannels.TASK_UPDATES:
                            await self._process_task_update(
                                TaskUpdate.model_validate_json(message["data"])
                            )
                        await self._handle_message(message["channel"], message["data"])
            except Exception as e:
                logger.error(
                    f"Manager {self.agent_type}: Error in listen_channels: {e}"
                )
            finally:
                await pubsub.unsubscribe(*channels)
                await pubsub.aclose()

    async def _process_query_message(self, data: QueryTask):
        logger.info(
            f"Manager {self.agent_type}: Processing query {data.query_id} for agents: {data.agents_needed}"
        )
        if self.agent_type not in data.agents_needed:
            logger.debug(f"Manager {self.agent_type}: Not needed for this query")
            return

        shared_key = RedisKeys.get_shared_data_key(data.query_id)
        shared_data_raw = await self.redis.json().get(shared_key)
        if not shared_data_raw:
            logger.error(
                f"Manager {self.agent_type}: No shared data found for query {data.query_id}"
            )
            return

        shared_data = SharedData(**shared_data_raw)
        agent_tasks = shared_data.get_tasks_for_agent(self.agent_type)
        logger.info(
            f"Manager {self.agent_type}: Found {len(agent_tasks)} tasks for agent"
        )
        if not agent_tasks:
            logger.warning(
                f"Manager {self.agent_type}: No tasks found for {self.agent_type}"
            )
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
            logger.info(
                f"Manager {self.agent_type}: Pushing task {task_node.task_id} to queue {queue_key}"
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
        elif task_update.agent_type != CHAT_AGENT_TYPE:  # ChatAgent is final
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

            queue_key = RedisKeys.get_agent_queue(self.agent_type)
            task_data = await self.redis.lpop(queue_key)
            logger.info(
                f"Manager {self.agent_type}: Checking queue {queue_key}, task_data: {task_data is not None}"
            )
            if task_data:
                task = TaskQueueItem.model_validate_json(task_data)

                shared_data: SharedData = await get_shared_data(
                    self.redis, task.query_id
                )
                conversation_id = shared_data.conversation_id

                channel = RedisChannels.get_command_channel(self.agent_type)
                message = CommandMessage(
                    agent_type=self.agent_type,
                    command="execute",
                    query_id=task.query_id,
                    conversation_id=conversation_id,
                    sub_query=task.sub_query,
                )
                await self.redis.publish(channel, json.dumps(message.model_dump()))
                logger.info(
                    f"Manager {self.agent_type}: Executing task on {self.agent_type}: {task.sub_query}"
                )

        except Exception as e:
            logger.error(
                f"Manager {self.agent_type}: Failed to execute next task for {self.agent_type}: {e}"
            )

    async def start(self):
        await self.listen_channels()
