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
from src.typing.redis.constants import BroadcastMessage, MessageType
from src.utils.agent_helpers import listen_pubsub_channels
from src.utils.redis_lock import redis_lock

logger = logging.getLogger(__name__)

# TTL for task queues (in seconds) - tasks expire after this time if not processed
TASK_QUEUE_TTL = 600  # 10 minutes - adjust based on your needs


class BaseManager:
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self._running = False
        self.redis = get_async_redis_connection().client

    async def start(self):
        self._running = True
        await self.listen_channels()

    async def stop(self):
        self._running = False

    # ==================== PUB/SUB LISTENER ====================

    async def listen_channels(self):
        async def handler(channel: str, data: bytes):
            if channel == RedisChannels.QUERY_CHANNEL:
                await self.on_query(QueryTask.model_validate_json(data))
            elif channel == RedisChannels.TASK_UPDATES:
                await self.on_task_update(TaskUpdate.model_validate_json(data))

        await listen_pubsub_channels(
            self.redis,
            [RedisChannels.QUERY_CHANNEL, RedisChannels.TASK_UPDATES],
            handler,
            lambda: self._running,
        )

    async def broadcast_thinking(self, query_id: str, message: str) -> None:
        """Broadcast thinking/status message to frontend."""
        try:
            broadcast = BroadcastMessage(
                type=MessageType.THINKING,
                data={
                    "reasoning": message,
                    "agent_type": self.agent_type,
                },
            )
            channel = RedisChannels.get_query_updates_channel(query_id)
            await self.redis.publish(channel, broadcast.model_dump_json())
        except Exception:
            pass

    async def on_query(self, data: QueryTask):
        if self.agent_type not in data.agents_needed:
            return

        shared_data = await self.get_shared_data(data.query_id)
        if not shared_data:
            logger.error(
                f"Manager {self.agent_type}: No shared data for {data.query_id}"
            )
            return

        tasks = shared_data.get_tasks_for_agent(self.agent_type)
        if not tasks:
            return

        active_count = 0
        pending_count = 0

        # Use pipeline for batch operations
        pipe = self.redis.pipeline()
        queues_to_update = set()

        for task in tasks:
            item = TaskQueueItem(
                query_id=data.query_id,
                sub_query=task.sub_query,
                task_id=task.task_id,
            )
            # Deps OK → active, else → pending
            is_ready = self.is_dependency_oke(task, shared_data)
            queue = (
                RedisKeys.get_agent_queue(self.agent_type)
                if is_ready
                else RedisKeys.get_agent_pending_queue(self.agent_type)
            )
            pipe.rpush(queue, item.model_dump_json())
            queues_to_update.add(queue)

            if is_ready:
                active_count += 1
            else:
                pending_count += 1

        # Set TTL for all queues that were updated
        for queue in queues_to_update:
            pipe.expire(queue, TASK_QUEUE_TTL)

        await pipe.execute()

        logger.info(
            f"Manager {self.agent_type}: Queued {len(tasks)} tasks "
            f"(active: {active_count}, pending: {pending_count}) with TTL={TASK_QUEUE_TTL}s"
        )

    async def on_task_update(self, update: TaskUpdate):
        if not update.query_id:
            return

        shared_data = await self.get_shared_data(update.query_id)
        if not shared_data:
            return

        if self.has_pending_tasks_affected_by_update(shared_data, update):
            await self.promote_pending(update.query_id)

    # ==================== PENDING → ACTIVE ====================

    async def promote_pending(self, query_id: str):
        lock_key = f"promote_pending:{self.agent_type}"

        try:
            async with redis_lock(
                self.redis,
                lock_key,
                timeout=5.0,
                retry_delay=0.05,
                max_retries=20,
                raise_on_failure=False,  # Don't fail, just skip if can't acquire
            ) as lock:
                if not await lock.is_owned():
                    logger.debug(
                        f"Manager {self.agent_type}: Skipping promotion for {query_id} "
                        "(lock not acquired, likely handled by another instance)"
                    )
                    return

                await self.promote_pending_locked(query_id)

        except Exception as e:
            logger.error(
                f"Manager {self.agent_type}: Error in promote_pending for {query_id}: {e}",
                exc_info=True,
            )

    async def promote_pending_locked(self, query_id: str):
        pending_key = RedisKeys.get_agent_pending_queue(self.agent_type)
        active_key = RedisKeys.get_agent_queue(self.agent_type)

        pending_raw = await self.redis.lrange(pending_key, 0, -1)
        if not pending_raw:
            return

        shared_data = await self.get_shared_data(query_id)
        if not shared_data:
            return

        ready_tasks = []

        for raw in pending_raw:
            task = TaskQueueItem.model_validate_json(raw)

            if task.query_id != query_id:
                continue

            task_node = self.find_task(task, shared_data)
            if task_node and self.is_dependency_oke(task_node, shared_data):
                ready_tasks.append((raw, task))

        if not ready_tasks:
            return
        pipe = self.redis.pipeline()

        for raw, task in ready_tasks:
            # LREM: Remove first occurrence of this exact task from pending
            pipe.lrem(pending_key, 1, raw)
            # RPUSH: Add to active queue
            pipe.rpush(active_key, raw)

        # Refresh TTL for both queues after promotion
        pipe.expire(active_key, TASK_QUEUE_TTL)
        pipe.expire(pending_key, TASK_QUEUE_TTL)

        await pipe.execute()

        logger.info(
            f"Manager {self.agent_type}: Promoted {len(ready_tasks)} tasks "
            f"for query {query_id} with refreshed TTL"
        )

    # ==================== HELPERS ====================

    def has_pending_tasks_affected_by_update(
        self, shared_data: SharedData, update: TaskUpdate
    ) -> bool:
        """
        Check if the task update might affect any pending tasks for this agent.

        Only promote if:
        1. Update is for a task that completed (DONE/COMPLETED status)
        2. There are tasks for this agent in the query
        3. Some of those tasks might depend on the completed task

        This optimization reduces unnecessary promotion attempts and lock contention.
        """
        if update.status not in [TaskStatus.DONE, TaskStatus.COMPLETED]:
            return False

        our_tasks = shared_data.get_tasks_for_agent(self.agent_type)
        if not our_tasks:
            return False

        for task in our_tasks:
            deps = getattr(task, "dependencies", None) or []
            if not deps:
                continue

            if update.task_id in deps:
                task_execution = shared_data.tasks.get(task.task_id)
                if task_execution and task_execution.status != TaskStatus.COMPLETED:
                    return True

        return False

    def is_dependency_oke(self, task_node, shared_data: SharedData) -> bool:
        deps = getattr(task_node, "dependencies", None) or []
        for dep_id in deps:
            dep = shared_data.tasks.get(dep_id)
            if not dep or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def find_task(self, item: TaskQueueItem, shared_data: SharedData):
        for t in shared_data.get_tasks_for_agent(self.agent_type):
            if t.task_id == item.task_id or t.sub_query == item.sub_query:
                return t
        return None

    async def get_shared_data(self, query_id: str) -> SharedData | None:
        raw = await self.redis.json().get(RedisKeys.get_shared_data_key(query_id))
        return SharedData(**raw) if raw else None
