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
from src.utils.redis_lock import redis_lock

logger = logging.getLogger(__name__)


class BaseManager:
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self._running = False
        self._redis_manager = get_async_redis_connection()
        self.redis = self._redis_manager.client

    async def start(self):
        self._running = True
        await self.listen_channels()

    async def stop(self):
        self._running = False

    # ==================== PUB/SUB LISTENER ====================

    async def listen_channels(self):
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

        shared_data = await self._get_shared_data(update.query_id)
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

        shared_data = await self._get_shared_data(query_id)
        if not shared_data:
            return

        ready_tasks = []

        for raw in pending_raw:
            task = TaskQueueItem.model_validate_json(raw)

            if task.query_id != query_id:
                continue

            task_node = self._find_task(task, shared_data)
            if task_node and self._deps_ok(task_node, shared_data):
                ready_tasks.append((raw, task))

        if not ready_tasks:
            return
        pipe = self.redis.pipeline()

        for raw, task in ready_tasks:
            # LREM: Remove first occurrence of this exact task from pending
            pipe.lrem(pending_key, 1, raw)
            # RPUSH: Add to active queue
            pipe.rpush(active_key, raw)

        await pipe.execute()

        logger.info(
            f"Manager {self.agent_type}: Promoted {len(ready_tasks)} tasks "
            f"for query {query_id}"
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

    async def get_queue_stats(self) -> dict:
        """Get queue statistics for monitoring."""
        active_key = RedisKeys.get_agent_queue(self.agent_type)
        pending_key = RedisKeys.get_agent_pending_queue(self.agent_type)

        active_count = await self.redis.llen(active_key)
        pending_count = await self.redis.llen(pending_key)

        # Group by query_id
        pending_raw = await self.redis.lrange(pending_key, 0, -1)
        pending_by_query = {}

        for raw in pending_raw:
            try:
                task = TaskQueueItem.model_validate_json(raw)
                query_id = task.query_id
                pending_by_query[query_id] = pending_by_query.get(query_id, 0) + 1
            except Exception:
                pass

        return {
            "agent_type": self.agent_type,
            "active_queue_size": active_count,
            "pending_queue_size": pending_count,
            "pending_by_query": pending_by_query,
        }

    async def check_stuck_pending_tasks(self) -> list:
        """
        Check for tasks stuck in pending queue.

        Returns list of potentially stuck tasks (dependencies satisfied but still pending).
        Useful for monitoring and debugging race conditions.
        """
        pending_key = RedisKeys.get_agent_pending_queue(self.agent_type)
        pending_raw = await self.redis.lrange(pending_key, 0, -1)

        stuck_tasks = []

        for raw in pending_raw:
            try:
                task = TaskQueueItem.model_validate_json(raw)

                # Check if dependencies are actually satisfied
                shared_data = await self._get_shared_data(task.query_id)
                if not shared_data:
                    continue

                task_node = self._find_task(task, shared_data)
                if not task_node:
                    stuck_tasks.append(
                        {
                            "task_id": task.task_id,
                            "query_id": task.query_id,
                            "sub_query": task.sub_query[:100],
                            "reason": "Task node not found in SharedData",
                        }
                    )
                    continue

                # Check if dependencies are satisfied but task still pending
                if self._deps_ok(task_node, shared_data):
                    stuck_tasks.append(
                        {
                            "task_id": task.task_id,
                            "query_id": task.query_id,
                            "sub_query": task.sub_query[:100],
                            "reason": "Dependencies satisfied but still in pending queue (possible race condition victim)",
                            "dependencies": getattr(task_node, "dependencies", []),
                        }
                    )

            except Exception as e:
                logger.error(f"Error checking stuck task: {e}")

        return stuck_tasks
