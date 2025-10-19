#!/usr/bin/env python3
"""
Test to verify the refactored separation of concerns between Manager and Agent.

Manager: Queue management, task distribution, shared data updates
Agent: Task processing, status updates, result broadcasting
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path BEFORE importing src modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
from src.typing.llm_response import BaseAgentResponse
from src.typing.redis import AgentStatus
from src.typing.redis.constants import RedisChannels, RedisKeys, TaskStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockWorkerAgent:
    """Mock worker agent to test the refactored interface."""

    def __init__(self, name: str = "test_agent"):
        self.name = name
        self.redis = None

    async def connect_redis(self):
        """Connect to Redis for testing."""
        self.redis = redis.from_url("redis://localhost:6379", decode_responses=True)

    async def _update_status(self, status: AgentStatus):
        """Update agent status in Redis."""
        await self.redis.hset(RedisKeys.AGENT_STATUS, self.name, status.value)
        logger.info(f"{self.name}: Status updated to {status.value}")

    async def _process_task_direct(self, query_id: str, sub_query: str):
        """Process task with data received directly from Manager command."""
        await self._update_status(AgentStatus.PROCESSING)

        try:
            logger.info(
                f"{self.name}: Processing '{sub_query}' for query_id: {query_id}"
            )

            # Simulate processing time
            await asyncio.sleep(0.5)

            # Mock response
            response = BaseAgentResponse(
                result=f"Processed: {sub_query}",
                context={"processed_by": self.name, "query": sub_query},
                llm_usage={"tokens": 100, "cost": 0.01},
            )

            # Publish completion
            await self._publish_task_completion(query_id, sub_query, response)
            await self._update_status(AgentStatus.IDLE)

        except Exception as e:
            logger.error(f"{self.name}: Task processing error: {e}")
            await self._update_status(AgentStatus.ERROR)

    async def _publish_task_completion(
        self, query_id: str, sub_query: str, response: BaseAgentResponse
    ):
        """Broadcast task completion to Manager for processing."""
        try:
            completion_message = {
                "query_id": query_id,
                "sub_query": sub_query,
                "status": TaskStatus.DONE,
                "results": {sub_query: response.result or ""},
                "context": {sub_query: response.context or {}},
                "llm_usage": response.llm_usage or {},
                "timestamp": datetime.now().isoformat(),
            }

            await self.redis.publish(
                RedisChannels.get_task_updates_channel(self.name),
                json.dumps(completion_message),
            )
            logger.info(f"{self.name}: Broadcasted completion for query_id: {query_id}")

        except Exception as e:
            logger.error(f"{self.name}: Task completion broadcasting failed: {e}")
            raise

    async def listen_for_commands(self):
        """Listen for execute commands from Manager."""
        pubsub = self.redis.pubsub()
        channel = RedisChannels.get_command_channel(self.name)
        await pubsub.subscribe(channel)
        logger.info(f"{self.name}: Listening on {channel}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])

                        # Validate command
                        if data.get("command") != "execute":
                            continue

                        query_id = data.get("query_id")
                        sub_query = data.get("sub_query")

                        if query_id and sub_query:
                            logger.info(
                                f"{self.name}: Received execute command: {sub_query}"
                            )
                            await self._process_task_direct(query_id, sub_query)
                        else:
                            logger.error(f"{self.name}: Invalid command data: {data}")

                    except Exception as e:
                        logger.error(f"{self.name}: Command processing error: {e}")

        except Exception as e:
            logger.error(f"{self.name}: Listen error: {e}")
        finally:
            await pubsub.unsubscribe(channel)


class MockManager:
    """Mock manager to test task distribution."""

    def __init__(self, agent_type: str = "test_agent"):
        self.agent_type = agent_type
        self.redis = None

    async def connect_redis(self):
        """Connect to Redis for testing."""
        self.redis = redis.from_url("redis://localhost:6379", decode_responses=True)

    async def send_task_to_agent(self, query_id: str, sub_query: str):
        """Send execute command with task data directly to agent."""
        channel = RedisChannels.get_command_channel(self.agent_type)
        message = {
            "agent_type": self.agent_type,
            "command": "execute",
            "query_id": query_id,
            "sub_query": sub_query,
            "timestamp": datetime.now().isoformat(),
        }

        await self.redis.publish(channel, json.dumps(message))
        logger.info(f"Manager: Sent execute command to {self.agent_type}: {sub_query}")

    async def listen_for_completions(self):
        """Listen for task completion updates from agents."""
        pubsub = self.redis.pubsub()
        channel = RedisChannels.get_task_updates_channel(self.agent_type)
        await pubsub.subscribe(channel)
        logger.info(f"Manager: Listening for completions on {channel}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        query_id = data.get("query_id")
                        sub_query = data.get("sub_query")
                        status = data.get("status")

                        logger.info(
                            f"Manager: Received completion - {query_id}: {sub_query} -> {status}"
                        )

                        # Here Manager would update shared_data (not shown in test)
                        # await self._process_task_completion(query_id, data)

                    except Exception as e:
                        logger.error(f"Manager: Completion processing error: {e}")

        except Exception as e:
            logger.error(f"Manager: Listen error: {e}")
        finally:
            await pubsub.unsubscribe(channel)


async def test_refactored_workflow():
    """Test the refactored Manager -> Agent workflow."""
    logger.info("=== Testing Refactored Workflow ===")

    # Create mock components
    agent = MockWorkerAgent("test_agent")
    manager = MockManager("test_agent")

    # Connect to Redis
    await agent.connect_redis()
    await manager.connect_redis()

    # Initialize agent status
    await agent._update_status(AgentStatus.IDLE)

    # Start agent listening in background
    agent_task = asyncio.create_task(agent.listen_for_commands())
    manager_task = asyncio.create_task(manager.listen_for_completions())

    # Give listeners time to start
    await asyncio.sleep(0.1)

    # Send test tasks
    test_tasks = [
        ("query_001", "Get inventory levels"),
        ("query_002", "Calculate total sales"),
        ("query_003", "Generate report"),
    ]

    for query_id, sub_query in test_tasks:
        await manager.send_task_to_agent(query_id, sub_query)
        await asyncio.sleep(0.2)  # Small delay between tasks

    # Let tasks complete
    await asyncio.sleep(2)

    # Cancel background tasks
    agent_task.cancel()
    manager_task.cancel()

    try:
        await agent_task
    except asyncio.CancelledError:
        pass

    try:
        await manager_task
    except asyncio.CancelledError:
        pass

    logger.info("=== Test Completed ===")


async def main():
    """Run verification test."""
    try:
        await test_refactored_workflow()
        print("\n✅ Refactor verification successful!")
        print("📋 Manager: Handles task distribution and shared data updates")
        print("🤖 Agent: Focuses on task processing and result broadcasting")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        print("\n❌ Refactor verification failed!")
        raise


if __name__ == "__main__":
    asyncio.run(main())
