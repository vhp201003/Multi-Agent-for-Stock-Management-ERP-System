# src/managers/base_manager.py
import json
import logging
from datetime import datetime

import redis.asyncio as redis
from redis.commands.json.path import Path
from src.typing.redis import AgentStatus
from src.typing.redis.constants import RedisChannels, RedisKeys, TaskStatus

logger = logging.getLogger(__name__)


class BaseManager:
    def __init__(self, agent_type: str, redis_url: str = "redis://localhost:6379"):
        self.agent_type = agent_type
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def get_pub_channels(self) -> list[str]:
        """Channels for publishing execute commands to agents."""
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def get_sub_channels(self) -> list[str]:
        """Channels for subscribing to query and task update events."""
        return [
            RedisChannels.QUERY_CHANNEL,
            RedisChannels.get_task_updates_channel(self.agent_type),
        ]

    async def listen_channels(self):
        """Listen to all subscribed channels using standardized pattern."""
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)
        logger.info(f"Manager for {self.agent_type} listening on {channels}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        channel = message["channel"]

                        # Route messages based on channel type
                        if channel == RedisChannels.QUERY_CHANNEL:
                            await self._handle_query_message(data)
                        elif channel == RedisChannels.get_task_updates_channel(
                            self.agent_type
                        ):
                            await self._handle_task_update_message(data)
                        else:
                            logger.warning(
                                f"Manager {self.agent_type}: Unknown channel {channel}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Manager {self.agent_type} message processing error: {e}"
                        )
        except redis.RedisError as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            channels = await self.get_sub_channels()
            await pubsub.unsubscribe(*channels)

    async def _try_execute_next_task(self):
        """Try to execute next task if agent is idle and tasks are available.

        This method is called reactively when:
        1. New query arrives (after pushing to queue)
        2. Task completion received (after processing update)

        No polling loop - purely event-driven.
        """
        # Check agent status first
        agent_status = await self._get_agent_status()

        # Only distribute if agent is idle
        if agent_status == AgentStatus.IDLE:
            # First check pending queue and move to active if dependencies met
            await self._process_pending_tasks()

            # Then check active queue for ready tasks
            await self._execute_ready_tasks()

    async def _process_pending_tasks(self):
        """Move tasks from pending to active queue if dependencies are satisfied."""
        pending_task = await self.redis.lpop(
            RedisKeys.get_agent_pending_queue(self.agent_type)
        )
        if pending_task:
            task = json.loads(pending_task)
            query_id = task["query_id"]

            # Check if dependencies are satisfied
            dependencies_done = await self._check_dependencies(query_id, task)

            if dependencies_done:
                # Move to active queue (push right - FIFO)
                await self.redis.rpush(
                    RedisKeys.get_agent_queue(self.agent_type), json.dumps(task)
                )
                logger.info(f"Moved task to active queue for {self.agent_type}: {task}")
            else:
                # Put back in pending queue (push right - maintain order)
                await self.redis.rpush(
                    RedisKeys.get_agent_pending_queue(self.agent_type), json.dumps(task)
                )

    async def _execute_ready_tasks(self):
        """Pop task from active queue and send execute command with task data."""
        # Pop task from active queue (pop left - FIFO)
        task_data = await self.redis.lpop(RedisKeys.get_agent_queue(self.agent_type))
        if task_data:
            try:
                task = json.loads(task_data)
                query_id = task["query_id"]
                sub_query = task["query"]

                # Send execute command with task data directly to agent
                await self._publish_execute_command(query_id, sub_query)
                logger.info(f"Sent execute command to {self.agent_type}: {task}")

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Invalid task data for {self.agent_type}: {e}")

    async def _check_dependencies(self, query_id: str, task: dict) -> bool:
        """Check if task dependencies are satisfied.

        Args:
            query_id: The query ID
            task: The task data

        Returns:
            bool: True if dependencies are satisfied
        """
        # Placeholder: Implement proper DAG dependency checking
        # This should check shared data to see if required agents have completed
        return True  # For now, assume dependencies are always met

    async def _publish_execute_command(self, query_id: str, sub_query: str):
        """Send execute command with task data directly to agent.

        Args:
            query_id: The query ID
            sub_query: The sub-query/task to execute
        """
        channel = RedisChannels.get_command_channel(self.agent_type)
        message = {
            "agent_type": self.agent_type,
            "command": "execute",
            "query_id": query_id,
            "sub_query": sub_query,  # Include task data in command
            "timestamp": datetime.now().isoformat(),
        }
        await self.publish_channel(channel, message)

    async def publish_channel(self, channel: str, message: dict):
        """Publish validated message to specified channel."""
        # Validate channel
        if channel not in await self.get_pub_channels():
            raise ValueError(f"BaseManager cannot publish to {channel}")

        try:
            await self.redis.publish(channel, json.dumps(message))
            logger.info(f"Manager {self.agent_type} published on {channel}: {message}")
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def _handle_query_message(self, data: dict):
        """Handle incoming query messages from orchestrator."""
        logger.info(f"Manager {self.agent_type} received query message: {data}")
        logger.info(f"Checking if {self.agent_type} in {data.get('agent_type', [])}")
        if self.agent_type in data.get("agent_type", []):
            query_id = data["query_id"]
            sub_queries = data.get("sub_query", {}).get(self.agent_type, [])
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data = await self.redis.json().get(shared_key)
            graph = None
            if shared_data:
                try:
                    graph = shared_data.get("graph")
                except (TypeError, AttributeError):
                    pass
            dependencies_done = True  # Placeholder: implement DAG check
            if graph:
                # graph_data = json.loads(graph)  # Placeholder for DAG check
                pass  # Implement DAG logic later
            queue_key = (
                RedisKeys.get_agent_queue(self.agent_type)
                if dependencies_done
                else RedisKeys.get_agent_pending_queue(self.agent_type)
            )
            for sub_query in sub_queries:
                task = {"query_id": query_id, "query": sub_query}
                await self.redis.rpush(queue_key, json.dumps(task))
                logger.info(f"Pushed task to {queue_key}: {task}")

            # Reactively try to execute tasks after pushing to queue
            await self._try_execute_next_task()
            logger.info(
                f"Triggered task execution check for {self.agent_type} after query"
            )

    async def _handle_task_update_message(self, data: dict):
        """Handle task completion updates from agents."""
        query_id = data.get("query_id")
        if not query_id:
            logger.error(f"Missing query_id in task update from {self.agent_type}")
            return

        # Process task completion
        await self._process_task_completion(query_id, data)
        logger.info(
            f"Processed completion update for {query_id} from {self.agent_type}"
        )

        # Reactively try to execute next task after completion
        await self._try_execute_next_task()
        logger.info(
            f"Triggered next task execution check for {self.agent_type} after completion"
        )

    async def _get_agent_status(self) -> AgentStatus:
        """Get current status of the agent from Redis.

        Returns:
            AgentStatus: Current status of the agent (default to IDLE if not set).
        """
        try:
            status_value = await self.redis.hget(
                RedisKeys.AGENT_STATUS, self.agent_type
            )
            if status_value:
                return AgentStatus(status_value)
            return AgentStatus.IDLE  # Default to idle if not set
        except Exception as e:
            logger.error(f"Error getting status for {self.agent_type}: {e}")
            return AgentStatus.IDLE  # Fallback to idle on error

    async def publish_command(self, query_id: str):
        """Legacy method - use _publish_execute_command instead.

        Kept for backward compatibility.

        Args:
            query_id (str): The unique identifier for the query.
        """
        logger.warning(
            f"Using legacy publish_command for {self.agent_type}. Use _publish_execute_command instead."
        )

        # For backward compatibility, try to get task from queue
        task_data = await self.redis.lindex(
            RedisKeys.get_agent_queue(self.agent_type), 0
        )
        if task_data:
            task = json.loads(task_data)
            sub_query = task.get("query", "")
            await self._publish_execute_command(query_id, sub_query)

    async def _process_task_completion(self, query_id: str, update: dict):
        """Process task completion and update shared data.

        Args:
            query_id: The query ID
            update: Task completion update data
        """
        try:
            # Update shared data using Redis JSON
            shared_key = RedisKeys.get_shared_data_key(query_id)
            current_data = await self.redis.json().get(shared_key)

            if current_data:
                data = current_data
            else:
                # Create minimal SharedData structure if not exists
                from datetime import datetime

                data = {
                    "original_query": f"Test query {query_id}",
                    "agents_needed": [self.agent_type],
                    "sub_queries": {self.agent_type: [update.get("sub_query", "")]},
                    "created_at": datetime.now().isoformat(),
                    "graph": {"nodes": {}, "edges": []},
                    "results": {},
                    "context": {},
                    "agents_done": [],
                    "status": "pending",
                    "llm_usage": {},
                }

            # Mark agent as done only if ALL tasks for this agent are completed
            if "agents_done" not in data:
                data["agents_done"] = []

            # Check if all sub-queries for this agent are now completed
            agent_sub_queries = data.get("sub_queries", {}).get(self.agent_type, [])
            agent_results = data.get("results", {}).get(self.agent_type, {})

            if (
                len(agent_results) >= len(agent_sub_queries)
                and self.agent_type not in data["agents_done"]
            ):
                data["agents_done"].append(self.agent_type)

            # Update results and context (merge instead of overwrite)
            if "results" not in data:
                data["results"] = {}
            if self.agent_type not in data["results"]:
                data["results"][self.agent_type] = {}
            data["results"][self.agent_type].update(update.get("results", {}))

            if "context" not in data:
                data["context"] = {}
            if self.agent_type not in data["context"]:
                data["context"][self.agent_type] = {}
            data["context"][self.agent_type].update(update.get("context", {}))

            # Update LLM usage if available
            if "llm_usage" not in data:
                data["llm_usage"] = {}
            data["llm_usage"][self.agent_type] = update.get("llm_usage", {})

            # Check if all agents are done and update status
            all_agents_needed = set(data.get("agents_needed", []))
            agents_done = set(data.get("agents_done", []))
            if all_agents_needed and all_agents_needed.issubset(agents_done):
                # All agents completed, mark as done
                data["status"] = TaskStatus.DONE
                logger.info(
                    f"All agents completed for query {query_id}, marking as done"
                )

                # Publish completion notification
                completion_message = {
                    "query_id": query_id,
                    "status": "completed",
                    "results": data.get("results", {}),
                    "context": data.get("context", {}),
                    "llm_usage": data.get("llm_usage", {}),
                    "agents_done": data.get("agents_done", []),
                }
                await self.redis.publish(
                    RedisChannels.get_query_completion_channel(query_id),
                    json.dumps(completion_message),
                )
                logger.info(f"Published completion notification for query {query_id}")

            # Validate and save with Pydantic using Redis JSON
            from src.typing.redis import SharedData

            validated = SharedData(**data)
            await self.redis.json().set(
                shared_key, Path.root_path(), validated.model_dump()
            )

            # Trigger next dependent tasks
            await self.check_and_trigger_next(query_id)

        except Exception as e:
            logger.error(f"Error processing task completion for {query_id}: {e}")
            raise

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
        """Start the BaseManager with event-driven architecture.

        No more polling loops - purely reactive to Redis events:
        - Query events trigger task queuing and execution
        - Task completion events trigger next task execution
        """
        logger.info(f"Starting BaseManager for {self.agent_type} in event-driven mode")
        await self.listen_channels()
