import asyncio
import logging

from src.communication import get_async_redis_connection
from src.typing.redis import (
    QueryTask,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskQueueItem,
    TaskStatus,
    TaskUpdate,
)

logger = logging.getLogger(__name__)


class BaseManager:
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self._running = False
        self._redis_manager = get_async_redis_connection()
        self.redis = self._redis_manager.client

    async def start(self):
        self._running = True
        await self._listen_channels()

    async def stop(self):
        self._running = False

    # ==================== PUB/SUB LISTENER ====================

    async def _listen_channels(self):
        """Listen for queries and task updates."""
        from src.utils.agent_helpers import listen_pubsub_channels

        async def handler(channel: str, data: bytes):
            if channel == RedisChannels.QUERY_CHANNEL:
                await self._on_query(QueryTask.model_validate_json(data))
            elif channel == RedisChannels.TASK_UPDATES:
                await self._on_task_update(TaskUpdate.model_validate_json(data))

        await listen_pubsub_channels(
            self.redis,
            [RedisChannels.QUERY_CHANNEL, RedisChannels.TASK_UPDATES],
            handler,
            lambda: self._running,
        )

    async def _on_query(self, data: QueryTask):
        """Query received → queue tasks for this agent."""
        if self.agent_type not in data.agents_needed:
            return

        shared_data = await self._get_shared_data(data.query_id)
        if not shared_data:
            logger.error(
                f"Manager {self.agent_type}: No shared data for {data.query_id}"
            )
            return

        tasks = shared_data.get_tasks_for_agent(self.agent_type)
        if not tasks:
            return

        for task in tasks:
            item = TaskQueueItem(
                query_id=data.query_id,
                sub_query=task.sub_query,
                task_id=task.task_id,
            )
            # Deps OK → active, else → pending
            queue = (
                RedisKeys.get_agent_queue(self.agent_type)
                if self._deps_ok(task, shared_data)
                else RedisKeys.get_agent_pending_queue(self.agent_type)
            )
            await self.redis.rpush(queue, item.model_dump_json())

        logger.info(f"Manager {self.agent_type}: Queued {len(tasks)} tasks")

    async def _on_task_update(self, update: TaskUpdate):
        """Task completed → check if pending tasks can be promoted."""
        if not update.query_id:
            return
        await asyncio.sleep(0.05)  # Wait for SharedData sync
        await self._promote_pending(update.query_id)


    # ==================== PENDING → ACTIVE ====================

    async def _promote_pending(self, query_id: str):
        """Move ready pending tasks to active queue."""
        pending_key = RedisKeys.get_agent_pending_queue(self.agent_type)
        active_key = RedisKeys.get_agent_queue(self.agent_type)

        pending_raw = await self.redis.lrange(pending_key, 0, -1)
        if not pending_raw:
            return

        shared_data = await self._get_shared_data(query_id)
        if not shared_data:
            return

        ready, still_pending = [], []

        for raw in pending_raw:
            task = TaskQueueItem.model_validate_json(raw)

            # Skip other queries
            if task.query_id != query_id:
                still_pending.append(raw)
                continue

            task_node = self._find_task(task, shared_data)
            if task_node and self._deps_ok(task_node, shared_data):
                ready.append(raw)
            else:
                still_pending.append(raw)

        if ready:
            pipe = self.redis.pipeline()
            pipe.delete(pending_key)
            if still_pending:
                pipe.rpush(pending_key, *still_pending)
            pipe.rpush(active_key, *ready)
            await pipe.execute()
            logger.info(f"Manager {self.agent_type}: Promoted {len(ready)} tasks")

    # ==================== HELPERS ====================

    def _deps_ok(self, task_node, shared_data: SharedData) -> bool:
        """Check if all dependencies completed."""
        deps = getattr(task_node, "dependencies", None) or []
        for dep_id in deps:
            dep = shared_data.tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def _find_task(self, item: TaskQueueItem, shared_data: SharedData):
        """Find task node by task_id or sub_query."""
        for t in shared_data.get_tasks_for_agent(self.agent_type):
            if t.task_id == item.task_id or t.sub_query == item.sub_query:
                return t
        return None

    async def _get_shared_data(self, query_id: str) -> SharedData | None:
        """Fetch SharedData from Redis."""
        raw = await self.redis.json().get(RedisKeys.get_shared_data_key(query_id))
        return SharedData(**raw) if raw else None
