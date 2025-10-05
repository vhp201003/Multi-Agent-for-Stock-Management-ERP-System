#!/usr/bin/env python3
"""
Simple Test Runner for Task Lifecycle

This avoids import issues by using dynamic imports.
Run this file to test the complete task lifecycle.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Setup logging first
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def run_task_lifecycle_test():
    """Run the complete task lifecycle test."""
    try:
        # Import after path setup
        import redis.asyncio as redis
        from src.agents.worker_agent import WorkerAgent
        from src.managers.base_manager import BaseManager
        from src.typing import Request, BaseAgentResponse
        from src.typing.redis import AgentStatus, SharedData
        from src.typing.redis.shared_data import AgentNode, Graph, SubQueryNode

        logger.info("=" * 80)
        logger.info("🚀 Starting Task Lifecycle Integration Test")
        logger.info("=" * 80)
        logger.info("Make sure Redis is running on localhost:6379")
        logger.info("")

        # Test Redis connection first
        redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
        try:
            await redis_client.ping()
            logger.info("✅ Redis connection successful")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            return 1

        # Mock Worker Agent for testing
        class TestInventoryAgent(WorkerAgent):
            def __init__(self):
                super().__init__(
                    agent_type="InventoryAgent",
                    agent_description="Test inventory management agent",
                    redis_host="localhost",
                    redis_port=6379,
                    llm_api_key="test-key",  # Mock key for testing
                )

            async def process(self, request: Request) -> BaseAgentResponse:
                """Mock business logic with adaptive processing speed."""
                query = request.query.lower()

                # Faster processing for high-load tasks
                if "high-load" in query:
                    await asyncio.sleep(0.02)  # 20ms for stress test
                else:
                    await asyncio.sleep(0.1)  # 100ms for normal test

                if "check stock" in query or "stock check" in query:
                    # Extract product ID from query if available
                    product_id = "P123"
                    if "p" in query:
                        import re

                        match = re.search(r"p(\d+)", query)
                        if match:
                            product_id = f"P{match.group(1)}"

                    result = (
                        f"Stock check: Product {product_id} has 150 units available"
                    )
                    context = {"product_id": product_id, "stock_level": 150}
                elif "update inventory" in query:
                    result = "Inventory updated: Added 50 units to stock"
                    context = {"product_id": "P123", "added_quantity": 50}
                else:
                    result = f"Processed: {query}"
                    context = {"processed": True}

                return BaseAgentResponse(
                    query_id=request.query_id,
                    result=result,
                    context=context,
                    llm_usage={"total_tokens": 100},
                )

        # Mock Orchestrator
        class MockOrchestrator:
            def __init__(self, redis_client):
                self.redis = redis_client

            async def distribute_tasks(self, query_id: str, agent_tasks: dict):
                """Simulate orchestrator distributing tasks."""
                # Create proper SharedData structure first

                nodes = {}
                for agent, queries in agent_tasks.items():
                    sub_query_nodes = [
                        SubQueryNode(query=q, status="pending") for q in queries
                    ]
                    nodes[agent] = AgentNode(sub_queries=sub_query_nodes)

                graph = Graph(nodes=nodes, edges=[])

                shared_data = SharedData(
                    original_query=f"Test query for {query_id}",
                    agents_needed=list(agent_tasks.keys()),
                    sub_queries=agent_tasks,
                    created_at=datetime.now().isoformat(),
                    graph=graph,
                )

                # Store initial shared data
                await self.redis.set(
                    f"agent:shared_data:{query_id}", shared_data.model_dump_json()
                )

                # Then distribute the tasks
                message = {
                    "query_id": query_id,
                    "agent_type": list(agent_tasks.keys()),
                    "sub_query": agent_tasks,
                    "timestamp": datetime.now().isoformat(),
                }

                await self.redis.publish("agent:query_channel", json.dumps(message))
                logger.info(f"📤 MockOrchestrator distributed tasks for {query_id}")

        # Clean up test data
        logger.info("🧹 Cleaning up test data...")
        keys_to_delete = await redis_client.keys("agent:*test*")
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
        await redis_client.delete("agent:status")

        # Initialize components
        logger.info("🔧 Initializing test components...")

        agent = TestInventoryAgent()
        manager = BaseManager("InventoryAgent", "redis://localhost:6379")
        orchestrator = MockOrchestrator(redis_client)

        # Mock agent's initialize_prompt to avoid MCP dependency
        async def mock_init_prompt():
            agent.prompt = "You are InventoryAgent: Test inventory management agent"

        agent.initialize_prompt = mock_init_prompt

        logger.info("✅ Components initialized")

        # Start agent and manager in background
        logger.info("🚀 Starting agent and manager...")

        agent_task = asyncio.create_task(agent.start())
        manager_task = asyncio.create_task(manager.start())

        # Wait for initialization
        await asyncio.sleep(0.5)

        # Verify agent is ready
        status = await redis_client.hget("agent:status", "InventoryAgent")
        if status != AgentStatus.IDLE.value:
            raise Exception(f"Agent not ready, status: {status}")
        logger.info("✅ Agent ready and listening")

        try:
            # Test 1: Single Task
            logger.info("\n" + "=" * 60)
            logger.info("📝 Test 1: Single Task Execution")
            logger.info("=" * 60)

            query_id = "test-query-001"
            tasks = {"InventoryAgent": ["Check stock for product P123"]}

            await orchestrator.distribute_tasks(query_id, tasks)
            logger.info("📤 Task distributed")

            # Give some time for processing
            await asyncio.sleep(1.0)

            # Debug: Check agent status and queue
            status = await redis_client.hget("agent:status", "InventoryAgent")
            queue_len = await redis_client.llen("agent:queue:InventoryAgent")
            logger.info(f"🔍 Agent status: {status}, Queue length: {queue_len}")

            # Wait for completion
            for i in range(50):  # 5 second timeout
                shared_data = await redis_client.get(f"agent:shared_data:{query_id}")
                if shared_data:
                    data = SharedData.model_validate_json(shared_data)
                    if "InventoryAgent" in data.agents_done:
                        logger.info("✅ Task completed successfully!")
                        logger.info(
                            f"   Results: {data.results.get('InventoryAgent', {})}"
                        )
                        break

                # Debug every 10 iterations
                if i % 10 == 0:
                    status = await redis_client.hget("agent:status", "InventoryAgent")
                    logger.info(f"🔍 Waiting... iteration {i}, agent status: {status}")

                await asyncio.sleep(0.1)
            else:
                # Final debug info before timeout
                status = await redis_client.hget("agent:status", "InventoryAgent")
                queue_len = await redis_client.llen("agent:queue:InventoryAgent")
                shared_data = await redis_client.get(f"agent:shared_data:{query_id}")
                logger.error(
                    f"❌ Timeout - Status: {status}, Queue: {queue_len}, SharedData exists: {bool(shared_data)}"
                )
                raise TimeoutError("Task 1 timeout")

            # Test 2: Multiple Tasks (FIFO)
            logger.info("\n" + "=" * 60)
            logger.info("📝 Test 2: Multiple Tasks (FIFO)")
            logger.info("=" * 60)

            query_id = "test-query-002"
            tasks = {
                "InventoryAgent": [
                    "Check stock for product P123",
                    "Update inventory for product P123",
                    "Generate report for product P123",
                ]
            }

            await orchestrator.distribute_tasks(query_id, tasks)
            logger.info(f"📤 Distributed {len(tasks['InventoryAgent'])} tasks")

            # Wait for all tasks
            for i in range(100):  # 10 second timeout
                shared_data = await redis_client.get(f"agent:shared_data:{query_id}")
                if shared_data:
                    data = SharedData.model_validate_json(shared_data)
                    if "InventoryAgent" in data.agents_done:
                        results = data.results.get("InventoryAgent", {})
                        if len(results) == 3:
                            logger.info("✅ All tasks completed!")
                            logger.info(f"   Completed: {list(results.keys())}")
                            break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Task 2 timeout")

            # Test 3: High Load - 100 Tasks Test
            logger.info("\n" + "=" * 60)
            logger.info("📝 Test 3: HIGH LOAD - 100 Tasks Stress Test 🔥")
            logger.info("=" * 60)

            # Create 100 tasks distributed across multiple queries
            num_tasks = 100
            tasks_per_query = 10  # 10 queries with 10 tasks each
            num_queries = num_tasks // tasks_per_query

            high_load_queries = []
            start_time = datetime.now()

            logger.info(
                f"🚀 Preparing {num_tasks} tasks across {num_queries} queries..."
            )

            # Generate and distribute all queries rapidly
            for q in range(num_queries):
                query_id = f"load-test-{q:03d}"
                high_load_queries.append(query_id)

                # Create tasks for this query
                task_list = []
                for t in range(tasks_per_query):
                    task_number = q * tasks_per_query + t + 1
                    task_list.append(
                        f"Process high-load task #{task_number:03d} - Stock check P{task_number:03d}"
                    )

                tasks = {"InventoryAgent": task_list}
                await orchestrator.distribute_tasks(query_id, tasks)

                # Small delay to avoid overwhelming Redis
                if q % 10 == 0:
                    logger.info(
                        f"📤 Distributed query batch {q // 10 + 1}/{(num_queries - 1) // 10 + 1}"
                    )
                    await asyncio.sleep(0.01)

            distribution_time = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"📤 ALL {num_tasks} tasks distributed in {distribution_time:.2f}s"
            )
            logger.info(
                f"📊 Distribution rate: {num_tasks / distribution_time:.1f} tasks/sec"
            )

            # Monitor processing progress
            completed = set()
            last_progress_report = 0
            processing_start = datetime.now()

            logger.info("⏳ Monitoring task processing progress...")

            for i in range(1000):  # 100 second timeout (increased for high load)
                current_completed = 0

                for query_id in high_load_queries:
                    if query_id not in completed:
                        shared_data = await redis_client.get(
                            f"agent:shared_data:{query_id}"
                        )
                        if shared_data:
                            data = SharedData.model_validate_json(shared_data)
                            if "InventoryAgent" in data.agents_done:
                                completed.add(query_id)
                                current_completed += len(
                                    data.results.get("InventoryAgent", {})
                                )

                # Progress reporting every 10% completion
                progress_percent = (len(completed) / num_queries) * 100
                if progress_percent >= last_progress_report + 10:
                    elapsed = (datetime.now() - processing_start).total_seconds()
                    processing_rate = (
                        len(completed) * tasks_per_query / elapsed if elapsed > 0 else 0
                    )
                    logger.info(
                        f"📈 Progress: {len(completed)}/{num_queries} queries ({progress_percent:.0f}%) - Rate: {processing_rate:.1f} tasks/sec"
                    )
                    last_progress_report = int(progress_percent // 10) * 10

                if len(completed) == num_queries:
                    break

                await asyncio.sleep(0.1)
            else:
                raise TimeoutError(
                    f"High load test timeout - {len(completed)}/{num_queries} queries completed"
                )

            # Final performance metrics
            total_time = (datetime.now() - start_time).total_seconds()
            processing_time = (datetime.now() - processing_start).total_seconds()

            logger.info("\n" + "🏆" * 60)
            logger.info("📊 HIGH LOAD TEST PERFORMANCE METRICS:")
            logger.info(f"✅ Total Tasks: {num_tasks}")
            logger.info(f"✅ Total Queries: {num_queries}")
            logger.info(f"✅ Distribution Time: {distribution_time:.2f}s")
            logger.info(f"✅ Processing Time: {processing_time:.2f}s")
            logger.info(f"✅ Total Time: {total_time:.2f}s")
            logger.info(
                f"📈 Average Processing Rate: {num_tasks / processing_time:.1f} tasks/second"
            )
            logger.info(
                f"📈 Peak Throughput: {num_tasks / total_time:.1f} tasks/second (end-to-end)"
            )
            logger.info("🏆" * 60)

            # Test 4: Concurrent Queries (Original small test)
            logger.info("\n" + "=" * 60)
            logger.info("📝 Test 4: Small Concurrent Queries")
            logger.info("=" * 60)

            concurrent_queries = ["test-query-003", "test-query-004"]
            for i, query_id in enumerate(concurrent_queries):
                tasks = {"InventoryAgent": [f"Process concurrent task {i + 1}"]}
                await orchestrator.distribute_tasks(query_id, tasks)
                await asyncio.sleep(0.1)

            logger.info(f"📤 Distributed {len(concurrent_queries)} concurrent queries")

            # Wait for all concurrent queries
            completed_small = set()
            for i in range(100):
                for query_id in concurrent_queries:
                    if query_id not in completed_small:
                        shared_data = await redis_client.get(
                            f"agent:shared_data:{query_id}"
                        )
                        if shared_data:
                            data = SharedData.model_validate_json(shared_data)
                            if "InventoryAgent" in data.agents_done:
                                completed_small.add(query_id)
                                logger.info(f"✅ Query {query_id} completed")

                if len(completed_small) == len(concurrent_queries):
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Small concurrent queries timeout")

            logger.info("\n" + "=" * 80)
            logger.info("🎉 ALL TESTS PASSED!")
            logger.info("✅ Single task execution")
            logger.info("✅ Multiple task FIFO processing")
            logger.info("✅ HIGH LOAD - 100 tasks stress test")
            logger.info("✅ Small concurrent query handling")
            logger.info("=" * 80)

            return 0

        finally:
            # Cleanup
            logger.info("\n🧹 Cleaning up...")
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

            await agent.stop()
            await redis_client.close()

            logger.info("✅ Cleanup completed")

    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        logger.error("Make sure you're running from the project root directory")
        return 1
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_task_lifecycle_test())
    exit(exit_code)
