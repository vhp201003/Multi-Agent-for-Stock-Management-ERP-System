import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from src.typing import BaseAgentRequest

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class WorkerAgent(BaseAgent):
    """Base class for worker agents (e.g., Inventory, Forecasting). Handles command execution and task updates."""

    async def get_pub_channels(self) -> List[str]:
        """Return list of channels this agent publishes to."""
        return [f"agent:task_updates:{self.name}"]

    async def get_sub_channels(self) -> List[str]:
        """Return list of channels this agent subscribes to."""
        return [f"agent:command_channel:{self.name}"]

    async def handle_message(self, channel: str, message: Dict[str, Any]):
        """Handle command messages and execute tasks accordingly.

        Processes 'execute' commands by popping tasks from the queue, processing
        the sub-query via the agent's process method, updating shared data,
        and publishing task completion updates.

        Args:
            channel (str): The channel the message was received on.
            message (Dict[str, Any]): The message data containing command details.
        """
        if channel == f"agent:command_channel:{self.name}":
            if message.get("command") == "execute":
                query_id = message["query_id"]
                # Pop task from queue
                task_data = await self.redis.rpop(f"agent:queue:{self.name}")
                if task_data:
                    task = json.loads(task_data)
                    sub_query = task["query"]
                    logger.info(
                        f"{self.name} processing sub_query: {sub_query} for query_id: {query_id}"
                    )
                    # Process the sub_query
                    request = BaseAgentRequest(query=sub_query, query_id=query_id)
                    response = await self.process(request)
                    # Update shared data
                    await self.update_shared_data(
                        query_id,
                        {
                            "results": {self.name: {sub_query: response.result or ""}},
                            "context": {self.name: {sub_query: response.context or {}}},
                            "llm_usage": {self.name: response.llm_usage or {}},
                        },
                    )
                    # Publish task update
                    await self.publish_message(
                        f"agent:task_updates:{self.name}",
                        {
                            "query_id": query_id,
                            "sub_query": sub_query,
                            "status": "done",
                            "results": {sub_query: response.result or ""},
                            "context": {sub_query: response.context or {}},
                            "timestamp": datetime.now().isoformat(),
                            "update_type": "task_completed",
                        },
                    )
                else:
                    logger.warning(f"No task in queue for {self.name}")

    async def process(self, request):
        """Process a worker request by calling LLM with worker-specific logic.

        Placeholder implementation. Subclasses should override with specific prompts and schemas.
        """
        # Placeholder: Implement LLM call for worker tasks
        raise NotImplementedError("WorkerAgent subclasses must implement process")

    async def start(self):
        """Start the WorkerAgent by listening to channels."""
        await self.listen_channels()
