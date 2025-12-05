import asyncio
import json
import logging

from src.communication import get_async_redis_connection
from src.typing.redis import (
    AgentStatus,
    CommandMessage,
    QueryTask,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskQueueItem,
    TaskStatus,
    TaskUpdate,
)
from src.utils import get_shared_data

logger = logging.getLogger(__name__)

# BLPOP timeout in seconds (0 = block forever, but we use finite for graceful shutdown)
BLPOP_TIMEOUT = 5


class BaseManager:
    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self._running = False

        self._redis_manager = get_async_redis_connection()
        self.redis = self._redis_manager.client

    async def get_sub_channels(self) -> list[str]:
        return [RedisChannels.QUERY_CHANNEL, RedisChannels.TASK_UPDATES]

    async def start(self):
        """Start the manager with pub/sub + blocking queue consumer."""
        self._running = True

        await asyncio.gather(
            self._listen_channels(),  # Pub/sub for query routing & task updates
            self._consume_queue(),  # BLPOP for task execution
        )

    async def stop(self):
        """Stop the manager gracefully."""
        self._running = False

    async def _listen_channels(self):
        """Listen for query assignments and task updates via pub/sub."""
        while self._running:
            pubsub = self.redis.pubsub()
            channels = await self.get_sub_channels()
            await pubsub.subscribe(*channels)

            try:
                async for message in pubsub.listen():
                    if not self._running:
                        break
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
            except Exception as e:
                logger.error(
                    f"Manager {self.agent_type}: Error in listen_channels: {e}"
                )
                await asyncio.sleep(1)
            finally:
                await pubsub.unsubscribe(*channels)
                await pubsub.aclose()

    async def _consume_queue(self):
        """Consume tasks from active queue using BLPOP (blocking).

        BLPOP is the optimal solution:
        - Zero CPU when idle (blocks waiting for data)
        - Instant reaction when task arrives
        - No polling overhead
        - Built-in timeout for graceful shutdown
        """
        logger.info(f"Manager {self.agent_type}: Starting queue consumer (BLPOP)")
        queue_key = RedisKeys.get_agent_queue(self.agent_type)

        while self._running:
            try:
                # Check if agent is idle
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
                    logger.info(f"Manager {self.agent_type}: Reset from ERROR state")
                    continue

                if agent_status != AgentStatus.IDLE:
                    # Agent is busy, wait a bit and check again
                    await asyncio.sleep(0.5)
                    continue

                # BLPOP: Block until task available or timeout
                # Returns (key, value) tuple or None on timeout
                result = await self.redis.blpop(queue_key, timeout=BLPOP_TIMEOUT)

                if result is None:
                    # Timeout - no task, loop continues (allows shutdown check)
                    continue

                _, task_data = result
                await self._dispatch_task(task_data)

            except Exception as e:
                logger.error(f"Manager {self.agent_type}: Queue consumer error: {e}")
                await asyncio.sleep(1)

    async def _dispatch_task(self, task_data: str):
        """Dispatch a task to the worker agent."""
        try:
            task = TaskQueueItem.model_validate_json(task_data)

            shared_data: SharedData = await get_shared_data(self.redis, task.query_id)
            if not shared_data:
                logger.error(
                    f"Manager {self.agent_type}: No shared data for query {task.query_id}"
                )
                return

            channel = RedisChannels.get_command_channel(self.agent_type)
            message = CommandMessage(
                agent_type=self.agent_type,
                command="execute",
                query_id=task.query_id,
                conversation_id=shared_data.conversation_id,
                sub_query=task.sub_query,
            )
            await self.redis.publish(channel, json.dumps(message.model_dump()))
            logger.info(
                f"Manager {self.agent_type}: Dispatched task: {task.sub_query[:50]}..."
            )

        except Exception as e:
            logger.error(f"Manager {self.agent_type}: Failed to dispatch task: {e}")

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

        # Note: _consume_queue will pick up tasks via BLPOP

    async def _process_task_update(self, task_update: TaskUpdate):
        """Handle task completion events - move dependent tasks to active queue."""
        query_id = task_update.query_id
        if not query_id:
            return

        # Small delay to ensure Orchestrator has updated SharedData
        await asyncio.sleep(0.05)

        # Check and move any pending tasks that are now ready
        await self._check_and_move_pending_tasks()

    async def _check_and_move_pending_tasks(self):
        """Check all pending tasks and move those with satisfied dependencies to active queue."""
        try:
            pending_queue_key = RedisKeys.get_agent_pending_queue(self.agent_type)
            active_queue_key = RedisKeys.get_agent_queue(self.agent_type)

            pending_tasks_raw = await self.redis.lrange(pending_queue_key, 0, -1)
            if not pending_tasks_raw:
                return

            ready_tasks = []
            still_pending = []

            for task_raw in pending_tasks_raw:
                task = TaskQueueItem(**json.loads(task_raw))

                # Get fresh SharedData for this task's query
                shared_data_raw = await self.redis.json().get(
                    RedisKeys.get_shared_data_key(task.query_id)
                )
                if not shared_data_raw:
                    still_pending.append(task_raw)
                    continue

                shared_data = SharedData(**shared_data_raw)

                # Find task node
                task_node = next(
                    (
                        t
                        for t in shared_data.get_tasks_for_agent(self.agent_type)
                        if t.task_id == task.task_id
                    ),
                    None,
                )

                if not task_node:
                    # Try to find by sub_query as fallback
                    task_node = next(
                        (
                            t
                            for t in shared_data.get_tasks_for_agent(self.agent_type)
                            if t.sub_query == task.sub_query
                        ),
                        None,
                    )

                if task_node and self._check_dependencies(task_node, shared_data):
                    ready_tasks.append(task_raw)
                    logger.info(
                        f"Manager {self.agent_type}: Task {task.task_id} dependencies satisfied"
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
                    f"Manager {self.agent_type}: Moved {len(ready_tasks)} tasks to active, "
                    f"{len(still_pending)} remain pending"
                )
                # Note: BLPOP in _consume_queue will pick these up automatically

        except Exception as e:
            logger.error(
                f"Manager {self.agent_type}: Failed to check pending tasks: {e}"
            )

    def _check_dependencies(self, task_node, shared_data: SharedData) -> bool:
        """Check if all dependencies of a task are completed.

        Supports both cross-agent and same-agent dependencies.
        E.g., inventory_2 depending on inventory_1 (same agent type)
        """
        if not task_node or not hasattr(task_node, "dependencies"):
            logger.warning(f"Invalid task_node provided: {task_node}")
            return False

        dependencies = getattr(task_node, "dependencies", [])
        if not dependencies:
            return True  # No dependencies = ready to execute

        for dep_id in dependencies:
            dep_exec = shared_data.tasks.get(dep_id)
            if not dep_exec:
                logger.debug(f"Dependency {dep_id} not found in shared_data")
                return False

            if dep_exec.status != TaskStatus.COMPLETED:
                logger.debug(
                    f"Dependency {dep_id} not completed (status: {dep_exec.status})"
                )
                return False

        return True

    # Backward compatibility
    async def _execute_next_available_task(self):
        """Deprecated: Tasks are now consumed via BLPOP in _consume_queue."""
        pass
