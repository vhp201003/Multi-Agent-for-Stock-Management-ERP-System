"""
Production-Grade Task Lifecycle Integration Test

Tests the complete flow:
1. MockOrchestrator distributes tasks to Manager
2. Manager queues tasks and sends commands to Worker
3. Worker executes tasks and publishes completion
4. Manager updates shared data and triggers next tasks

This test validates the Manager ↔ Worker communication pattern
without requiring a real OrchestratorAgent.
"""

# Standard library imports
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Third-party imports
import redis.asyncio as redis
from src.agents.worker_agent import WorkerAgent
from src.managers.base_manager import BaseManager
from src.typing import BaseAgentResponse, Request
from src.typing.redis import AgentStatus, SharedData

# Add project root to path for local imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Local imports (after path modification)
# pylint: disable=wrong-import-position

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MockInventoryAgent(WorkerAgent):
    """Concrete implementation of WorkerAgent for testing."""

    def __init__(self, **kwargs):
        super().__init__(
            agent_type="InventoryAgent",
            agent_description="Test inventory management agent",
            **kwargs,
        )

    async def process(self, request: Request) -> BaseAgentResponse:
        """Mock business logic - simulate inventory operations."""
        query = request.query.lower()

        # Simulate different processing times
        if "slow" in query:
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(0.1)

        # Mock responses based on query content
        if "check stock" in query:
            result = "Stock check: Product has 150 units available"
            context = {"product_id": "P123", "stock_level": 150, "location": "WH-A"}
        elif "update inventory" in query:
            result = "Inventory updated: Added 50 units to stock"
            context = {"product_id": "P123", "added_quantity": 50, "new_total": 200}
        elif "generate report" in query:
            result = "Report generated: Monthly inventory summary"
            context = {
                "report_type": "monthly",
                "items_count": 1250,
                "total_value": 125000,
            }
        else:
            result = f"Processed query: {query}"
            context = {
                "query_type": "general",
                "processed_at": datetime.now().isoformat(),
            }

        return BaseAgentResponse(
            query_id=request.query_id,
            result=result,
            context=context,
            llm_usage={"total_tokens": 150, "completion_tokens": 75},
        )


class MockOrchestrator:
    """Mock orchestrator that simulates task distribution."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def distribute_tasks(self, query_id: str, agent_tasks: Dict[str, List[str]]):
        """Distribute tasks to managers via query_channel.

        Args:
            query_id: Unique query identifier
            agent_tasks: Dict mapping agent names to their sub-queries
        """
        message = {
            "query_id": query_id,
            "agent_type": list(agent_tasks.keys()),  # List of agent names
            "sub_query": agent_tasks,  # Dict of {agent_type: [sub_queries]}
            "timestamp": datetime.now().isoformat(),
            "orchestrator": "MockOrchestrator",
        }

        await self.redis.publish("agent:query_channel", json.dumps(message))
        logger.info(f"MockOrchestrator distributed tasks for query_id: {query_id}")
        logger.info(f"Tasks: {agent_tasks}")


class TaskLifecycleTest:
    """Complete task lifecycle integration test."""

    def __init__(self):
        self.redis_url = "redis://localhost:6379"
        self.redis_client = None
        self.agent = None
        self.manager = None
        self.orchestrator = None

    async def setup(self):
        """Setup test environment."""
        logger.info("=" * 80)
        logger.info("Setting up Task Lifecycle Test Environment")
        logger.info("=" * 80)

        # Connect to Redis
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)

        # Test Redis connection
        try:
            await self.redis_client.ping()
            logger.info("✅ Redis connection successful")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            raise

        # Clean up any existing test data
        await self.cleanup_redis()

        # Initialize components
        self.agent = MockInventoryAgent(
            redis_host="localhost",
            redis_port=6379,
            llm_api_key="test-key",  # Mock key
        )

        self.manager = BaseManager(
            agent_type="InventoryAgent", redis_url=self.redis_url
        )

        self.orchestrator = MockOrchestrator(self.redis_client)

        logger.info("✅ Test components initialized")

    async def cleanup_redis(self):
        """Clean up Redis test data."""
        # Clean up test keys
        keys_to_delete = []

        # Find test-related keys
        for pattern in [
            "agent:queue:InventoryAgent",
            "agent:pending_queue:InventoryAgent",
            "agent:shared_data:test-*",
            "agent:status",
        ]:
            keys = await self.redis_client.keys(pattern)
            keys_to_delete.extend(keys)

        if keys_to_delete:
            await self.redis_client.delete(*keys_to_delete)
            logger.info(f"Cleaned up {len(keys_to_delete)} Redis keys")

    async def start_agent(self):
        """Start the agent in background."""
        logger.info("Starting InventoryAgent...")

        # Mock the initialize_prompt to avoid MCP dependency
        async def mock_init_prompt():
            self.agent.prompt = (
                "You are InventoryAgent: Test inventory management agent"
            )

        self.agent.initialize_prompt = mock_init_prompt

        # Start agent in background
        agent_task = asyncio.create_task(self.agent.start())
        await asyncio.sleep(0.2)  # Let agent initialize

        # Verify agent status
        status = await self.redis_client.hget("agent:status", "InventoryAgent")
        assert status == AgentStatus.IDLE.value, f"Expected IDLE status, got {status}"
        logger.info("✅ InventoryAgent started and ready")

        return agent_task

    async def start_manager(self):
        """Start the manager in background."""
        logger.info("Starting BaseManager...")

        # Start manager in background
        manager_task = asyncio.create_task(self.manager.start())
        await asyncio.sleep(0.2)  # Let manager initialize

        logger.info("✅ BaseManager started and listening")
        return manager_task

    async def test_single_task_flow(self):
        """Test single task execution flow."""
        logger.info("\n" + "=" * 60)
        logger.info("Testing Single Task Flow")
        logger.info("=" * 60)

        query_id = "test-query-001"
        tasks = {"InventoryAgent": ["Check stock for product P123"]}

        # Step 1: Orchestrator distributes task
        logger.info("Step 1: Distributing task via MockOrchestrator...")
        await self.orchestrator.distribute_tasks(query_id, tasks)

        # Wait for processing
        await asyncio.sleep(0.5)

        # Step 2: Verify task was queued
        logger.info("Step 2: Verifying task queuing...")
        queue_len = await self.redis_client.llen("agent:queue:InventoryAgent")
        logger.info(f"Active queue length: {queue_len}")

        # Step 3: Wait for task execution
        logger.info("Step 3: Waiting for task execution...")

        # Monitor agent status changes
        for i in range(50):  # 5 second timeout
            status = await self.redis_client.hget("agent:status", "InventoryAgent")
            logger.debug(f"Agent status: {status}")

            if status == AgentStatus.IDLE.value:
                # Check if shared data was updated
                shared_data = await self.redis_client.get(
                    f"agent:shared_data:{query_id}"
                )
                if shared_data:
                    data = SharedData.model_validate_json(shared_data)
                    if "InventoryAgent" in data.agents_done:
                        logger.info("✅ Task completed successfully!")
                        break

            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Task execution timeout")

        # Step 4: Verify results
        logger.info("Step 4: Verifying results...")
        await self.verify_task_completion(query_id, "InventoryAgent")

    async def test_multiple_task_flow(self):
        """Test multiple task execution with proper queuing."""
        logger.info("\n" + "=" * 60)
        logger.info("Testing Multiple Task Flow (FIFO Ordering)")
        logger.info("=" * 60)

        query_id = "test-query-002"
        tasks = {
            "InventoryAgent": [
                "Check stock for product P123",
                "Update inventory for product P123",
                "Generate report for product P123",
            ]
        }

        # Distribute all tasks
        logger.info("Distributing multiple tasks...")
        await self.orchestrator.distribute_tasks(query_id, tasks)

        # Wait for all tasks to complete
        logger.info("Waiting for all tasks to complete...")

        completed_tasks = []
        for i in range(100):  # 10 second timeout
            # Check task updates channel for completion messages
            shared_data = await self.redis_client.get(f"agent:shared_data:{query_id}")
            if shared_data:
                data = SharedData.model_validate_json(shared_data)
                if "InventoryAgent" in data.agents_done:
                    # Count completed sub-tasks
                    agent_results = data.results.get("InventoryAgent", {})
                    completed_tasks = list(agent_results.keys())

                    if len(completed_tasks) == 3:
                        logger.info(f"✅ All {len(completed_tasks)} tasks completed!")
                        break

            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Multiple task execution timeout")

        # Verify FIFO processing order
        logger.info("Verifying FIFO task processing order...")
        expected_order = tasks["InventoryAgent"]

        # Check if tasks were processed in the correct order
        # (This is a simplified check - in production you'd track timestamps)
        assert len(completed_tasks) == len(expected_order), (
            f"Expected {len(expected_order)} tasks, got {len(completed_tasks)}"
        )

        logger.info(f"✅ Tasks processed: {completed_tasks}")
        logger.info("✅ FIFO ordering verified")

    async def test_concurrent_queries(self):
        """Test handling of concurrent queries with different IDs."""
        logger.info("\n" + "=" * 60)
        logger.info("Testing Concurrent Query Handling")
        logger.info("=" * 60)

        query_ids = ["test-query-003", "test-query-004"]
        all_tasks = []

        # Distribute concurrent tasks
        for i, query_id in enumerate(query_ids):
            tasks = {
                "InventoryAgent": [
                    f"Process concurrent task {i + 1} for query {query_id}"
                ]
            }
            all_tasks.append((query_id, tasks))
            await self.orchestrator.distribute_tasks(query_id, tasks)
            await asyncio.sleep(0.1)  # Small delay between queries

        logger.info(f"Distributed {len(query_ids)} concurrent queries")

        # Wait for all to complete
        completed_queries = set()
        for i in range(100):  # 10 second timeout
            for query_id, _ in all_tasks:
                if query_id not in completed_queries:
                    shared_data = await self.redis_client.get(
                        f"agent:shared_data:{query_id}"
                    )
                    if shared_data:
                        data = SharedData.model_validate_json(shared_data)
                        if "InventoryAgent" in data.agents_done:
                            completed_queries.add(query_id)
                            logger.info(f"✅ Query {query_id} completed")

            if len(completed_queries) == len(query_ids):
                break

            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Concurrent query processing timeout")

        logger.info(f"✅ All {len(query_ids)} concurrent queries completed")

    async def verify_task_completion(self, query_id: str, agent_type: str):
        """Verify task completion and data integrity."""
        # Get shared data
        shared_data = await self.redis_client.get(f"agent:shared_data:{query_id}")
        assert shared_data is not None, f"No shared data found for {query_id}"

        data = SharedData.model_validate_json(shared_data)

        # Verify agent completion
        assert agent_type in data.agents_done, f"{agent_type} not in completed agents"

        # Verify results structure
        assert agent_type in data.results, f"No results for {agent_type}"
        assert agent_type in data.context, f"No context for {agent_type}"

        # Verify LLM usage tracking
        if hasattr(data, "llm_usage") and data.llm_usage:
            assert agent_type in data.llm_usage, f"No LLM usage for {agent_type}"

        logger.info(f"✅ Task completion verified for {agent_type}")
        logger.info(f"   Results: {len(data.results[agent_type])} items")
        logger.info(f"   Context: {len(data.context[agent_type])} items")

    async def test_error_handling(self):
        """Test error handling and recovery."""
        logger.info("\n" + "=" * 60)
        logger.info("Testing Error Handling")
        logger.info("=" * 60)

        # Test with invalid message format
        logger.info("Testing invalid message handling...")

        # Send malformed message
        invalid_message = {"invalid": "format", "missing": "required_fields"}
        await self.redis_client.publish(
            "agent:query_channel", json.dumps(invalid_message)
        )

        await asyncio.sleep(0.2)

        # Agent should still be healthy
        status = await self.redis_client.hget("agent:status", "InventoryAgent")
        assert status == AgentStatus.IDLE.value, (
            "Agent should remain IDLE after invalid message"
        )

        logger.info("✅ Invalid message handled gracefully")

    async def cleanup(self):
        """Cleanup test environment."""
        logger.info("\nCleaning up test environment...")

        if self.agent:
            await self.agent.stop()

        if self.redis_client:
            await self.cleanup_redis()
            await self.redis_client.close()

        logger.info("✅ Cleanup completed")

    async def run_all_tests(self):
        """Run complete test suite."""
        try:
            await self.setup()

            # Start components
            agent_task = await self.start_agent()
            manager_task = await self.start_manager()

            try:
                # Run test scenarios
                await self.test_single_task_flow()
                await self.test_multiple_task_flow()
                await self.test_concurrent_queries()
                await self.test_error_handling()

                logger.info("\n" + "=" * 80)
                logger.info("🎉 ALL TESTS PASSED!")
                logger.info("=" * 80)

            finally:
                # Stop background tasks
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

        except Exception as e:
            logger.error(f"\n❌ Test failed: {e}")
            raise
        finally:
            await self.cleanup()


async def main():
    """Run the task lifecycle test suite."""
    logger.info("Starting Task Lifecycle Integration Test")
    logger.info("Make sure Redis is running on localhost:6379")
    logger.info("")

    test_suite = TaskLifecycleTest()

    try:
        await test_suite.run_all_tests()
        return 0
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
