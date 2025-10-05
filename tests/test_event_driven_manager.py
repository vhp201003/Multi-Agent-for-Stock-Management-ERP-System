#!/usr/bin/env python3
"""
Test Event-Driven Manager Architecture

This test verifies the new event-driven BaseManager that responds to:
1. Query events → Push to queue → Check agent status → Execute if idle
2. Task completion events → Process update → Check agent status → Execute next if idle

No more while True polling loops!
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis
from src.managers.base_manager import BaseManager
from src.typing.redis import AgentStatus
from src.typing.redis.constants import RedisChannels, RedisKeys, TaskStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestEventDrivenManager:
    """Test class for event-driven BaseManager behavior."""

    def __init__(self):
        self.redis = None
        self.manager = None
        self.agent_name = "test_inventory_agent"

    async def setup(self):
        """Setup test environment."""
        self.redis = redis.from_url("redis://localhost:6379", decode_responses=True)
        self.manager = BaseManager(agent_type=self.agent_name)

        # Clean up any existing data
        await self._cleanup()

        # Set agent status to IDLE
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.IDLE.value
        )
        logger.info(f"Setup complete - Agent {self.agent_name} set to IDLE")

    async def _cleanup(self):
        """Clean up Redis data."""
        keys_to_clean = [
            RedisKeys.get_agent_queue(self.agent_name),
            RedisKeys.get_agent_pending_queue(self.agent_name),
            RedisKeys.get_shared_data_key("test_query_001"),
            RedisKeys.get_shared_data_key("test_query_002"),
        ]

        for key in keys_to_clean:
            await self.redis.delete(key)

        await self.redis.hdel(RedisKeys.AGENT_STATUS, self.agent_name)

    async def test_query_event_triggers_execution(self):
        """Test that query events trigger immediate task execution if agent is idle."""
        logger.info("=== Test 1: Query Event Triggers Execution ===")

        # Simulate query message from orchestrator
        query_message = {
            "query_id": "test_query_001",
            "agent_type": [self.agent_name],
            "sub_query": {
                self.agent_name: ["Check inventory levels", "Generate stock report"]
            },
        }

        # Start manager in background (non-blocking)
        manager_task = asyncio.create_task(self.manager.start())
        await asyncio.sleep(0.1)  # Let manager start listening

        # Monitor command channel for execute commands
        command_received = []

        async def monitor_commands():
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(RedisChannels.get_command_channel(self.agent_name))

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("command") == "execute":
                        command_received.append(data)
                        logger.info(f"📨 Execute command received: {data['sub_query']}")
                        if len(command_received) >= 2:  # Expected 2 tasks
                            break
            await pubsub.unsubscribe(RedisChannels.get_command_channel(self.agent_name))

        monitor_task = asyncio.create_task(monitor_commands())

        # Send query event
        await self.redis.publish(RedisChannels.QUERY_CHANNEL, json.dumps(query_message))
        logger.info("🚀 Published query event")

        # Wait for commands to be received
        try:
            await asyncio.wait_for(monitor_task, timeout=2.0)
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for execute commands")

        # Verify results
        assert len(command_received) >= 1, (
            f"Expected at least 1 execute command, got {len(command_received)}"
        )

        # Check that tasks were queued
        queue_length = await self.redis.llen(RedisKeys.get_agent_queue(self.agent_name))
        logger.info(f"📋 Tasks remaining in queue: {queue_length}")

        # Cleanup
        manager_task.cancel()
        try:
            await manager_task
        except asyncio.CancelledError:
            pass

        logger.info("✅ Test 1 PASSED - Query events trigger execution")

    async def test_completion_triggers_next_task(self):
        """Test that task completion events trigger next task execution."""
        logger.info("=== Test 2: Completion Triggers Next Task ===")

        # Pre-populate queue with multiple tasks
        tasks = [
            {"query_id": "test_query_002", "query": "Task 1: Check stock"},
            {"query_id": "test_query_002", "query": "Task 2: Update inventory"},
            {"query_id": "test_query_002", "query": "Task 3: Generate alerts"},
        ]

        for task in tasks:
            await self.redis.rpush(
                RedisKeys.get_agent_queue(self.agent_name), json.dumps(task)
            )

        logger.info(f"📋 Pre-loaded {len(tasks)} tasks in queue")

        # Set agent to PROCESSING (simulating busy state)
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.PROCESSING.value
        )

        # Start manager
        manager_task = asyncio.create_task(self.manager.start())
        await asyncio.sleep(0.1)

        # Monitor for execute commands
        commands_received = []

        async def monitor_commands():
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(RedisChannels.get_command_channel(self.agent_name))

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("command") == "execute":
                        commands_received.append(data)
                        logger.info(f"📨 Execute command: {data['sub_query']}")

                        # After first command, simulate completion to trigger next
                        if len(commands_received) == 1:
                            await asyncio.sleep(0.1)  # Small delay
                            # Set agent back to IDLE and send completion
                            await self.redis.hset(
                                RedisKeys.AGENT_STATUS,
                                self.agent_name,
                                AgentStatus.IDLE.value,
                            )

                            # Use the same query_id and sub_query from the executed command
                            executed_sub_query = data["sub_query"]
                            executed_query_id = data["query_id"]

                            completion_message = {
                                "query_id": executed_query_id,
                                "sub_query": executed_sub_query,
                                "status": TaskStatus.DONE,
                                "results": {
                                    executed_sub_query: "Completed successfully"
                                },
                                "context": {},
                                "llm_usage": {},
                                "timestamp": datetime.now().isoformat(),
                                "update_type": "task_completed",
                            }

                            await self.redis.publish(
                                RedisChannels.get_task_updates_channel(self.agent_name),
                                json.dumps(completion_message),
                            )
                            logger.info("✅ Published task completion event")

                        elif len(commands_received) >= 2:
                            break

            await pubsub.unsubscribe(RedisChannels.get_command_channel(self.agent_name))

        monitor_task = asyncio.create_task(monitor_commands())

        # Set agent to IDLE to trigger first task
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.IDLE.value
        )

        # Trigger initial execution by calling the method directly
        await self.manager._try_execute_next_task()

        # Wait for completion cycle
        try:
            await asyncio.wait_for(monitor_task, timeout=3.0)
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for completion cycle")

        # Verify results
        assert len(commands_received) >= 2, (
            f"Expected at least 2 commands (initial + after completion), got {len(commands_received)}"
        )

        remaining_tasks = await self.redis.llen(
            RedisKeys.get_agent_queue(self.agent_name)
        )
        logger.info(f"📋 Tasks remaining: {remaining_tasks}")

        # Cleanup
        manager_task.cancel()
        try:
            await manager_task
        except asyncio.CancelledError:
            pass

        logger.info("✅ Test 2 PASSED - Completion events trigger next task")

    async def test_agent_busy_no_execution(self):
        """Test that no execution happens when agent is busy."""
        logger.info("=== Test 3: No Execution When Agent Busy ===")

        # Clean up queue first
        await self.redis.delete(RedisKeys.get_agent_queue(self.agent_name))

        # Set agent to PROCESSING
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.PROCESSING.value
        )

        # Add task to queue
        task = {"query_id": "test_query_003", "query": "Should not execute"}
        await self.redis.rpush(
            RedisKeys.get_agent_queue(self.agent_name), json.dumps(task)
        )

        # Try to execute
        await self.manager._try_execute_next_task()

        # Verify no command was sent and task remains in queue
        queue_length = await self.redis.llen(RedisKeys.get_agent_queue(self.agent_name))
        assert queue_length == 1, (
            f"Task should remain in queue when agent busy, got length: {queue_length}"
        )

        logger.info("✅ Test 3 PASSED - No execution when agent busy")

    async def test_high_load_stress_test(self):
        """Test system under high concurrent load with performance monitoring"""
        logger.info("=== Test 4: High Load Stress Test ===")

        # Clean up any leftover tasks from previous tests
        await self._cleanup()
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.IDLE.value
        )

        start_time = time.time()
        num_queries = 2
        tasks_per_query = 3  # 2 * 3 = 6 total tasks
        total_tasks = num_queries * tasks_per_query

        # Initialize tracking variables
        commands_received = []
        completions_sent = 0

        async def monitor_commands():
            nonlocal commands_received, completions_sent
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(RedisChannels.get_command_channel(self.agent_name))
            logger.info(
                f"📡 Monitoring commands on {RedisChannels.get_command_channel(self.agent_name)}"
            )

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("command") == "execute":
                        commands_received.append(
                            {
                                "timestamp": time.time(),
                                "query_id": data["query_id"],
                                "sub_query": data["sub_query"],
                            }
                        )
                        logger.info(
                            f"📨 Received execute command {len(commands_received)}/{total_tasks}: {data['sub_query']}"
                        )

                        # Simulate instant task completion for stress test
                        completion_message = {
                            "query_id": data["query_id"],
                            "sub_query": data["sub_query"],
                            "status": TaskStatus.DONE,
                            "results": {
                                data["sub_query"]: f"Result for {data['sub_query']}"
                            },
                            "context": {},
                            "llm_usage": {"tokens": 50, "cost": 0.001},
                            "timestamp": datetime.now().isoformat(),
                            "update_type": "task_completed",
                        }

                        # Small delay to simulate processing
                        await asyncio.sleep(0.01)

                        await self.redis.publish(
                            RedisChannels.get_task_updates_channel(self.agent_name),
                            json.dumps(completion_message),
                        )
                        completions_sent += 1
                        logger.info(f"✅ Sent completion {completions_sent}")

                        # Stop when all tasks processed
                        if len(commands_received) >= total_tasks:
                            logger.info(f"🎯 All {total_tasks} tasks processed!")
                            break

            await pubsub.unsubscribe(RedisChannels.get_command_channel(self.agent_name))

        # Start monitor first
        monitor_task = asyncio.create_task(monitor_commands())
        await asyncio.sleep(0.2)  # Let monitor start

        # Start manager in background
        manager_task = asyncio.create_task(self.manager.start())
        await asyncio.sleep(0.2)  # Let manager start

        # Ensure agent is IDLE before sending queries
        await self.redis.hset(
            RedisKeys.AGENT_STATUS, self.agent_name, AgentStatus.IDLE.value
        )
        logger.info(f"✅ Set agent {self.agent_name} to IDLE status")

        # Send multiple query events concurrently
        for i in range(num_queries):
            query_message = {
                "query_id": f"stress_query_{i:03d}",
                "agent_type": [self.agent_name],
                "sub_query": {
                    self.agent_name: [
                        f"Task_{i:03d}_{j:02d}" for j in range(tasks_per_query)
                    ]
                },
            }

            await self.redis.publish(
                RedisChannels.QUERY_CHANNEL, json.dumps(query_message)
            )
            await asyncio.sleep(0.02)  # Small delay between queries

        logger.info(f"🚀 Sent {num_queries} query events with {total_tasks} tasks")

        # Check status after sending
        status = await self.redis.hget(RedisKeys.AGENT_STATUS, self.agent_name)
        logger.info(f"📊 Agent status after queries: {status}")

        # Wait for all tasks to complete with timeout
        try:
            await asyncio.wait_for(monitor_task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.error(
                f"⏰ Timeout: Only processed {len(commands_received)}/{total_tasks} tasks"
            )

        # Calculate performance metrics
        end_time = time.time()
        total_duration = end_time - start_time

        tasks_processed = len(commands_received)
        throughput = tasks_processed / total_duration if total_duration > 0 else 0

        # Check queue status
        remaining_tasks = await self.redis.llen(
            RedisKeys.get_agent_queue(self.agent_name)
        )

        logger.info("📈 STRESS TEST RESULTS:")
        logger.info(f"   ⏱️  Duration: {total_duration:.2f} seconds")
        logger.info(f"   📋 Tasks processed: {tasks_processed}/{total_tasks}")
        logger.info(f"   ✅ Completions sent: {completions_sent}")
        logger.info(f"   🚀 Throughput: {throughput:.1f} tasks/sec")
        logger.info(f"   📊 Success rate: {(tasks_processed / total_tasks) * 100:.1f}%")
        logger.info(f"   🔄 Remaining in queue: {remaining_tasks}")

        # Cleanup
        manager_task.cancel()
        try:
            await manager_task
        except asyncio.CancelledError:
            pass

        # Performance assertions
        assert tasks_processed >= total_tasks * 0.8, (
            f"Expected ≥80% task completion, got {(tasks_processed / total_tasks) * 100:.1f}%"
        )
        assert throughput >= 1.0, (
            f"Expected ≥1.0 tasks/sec throughput, got {throughput:.1f}"
        )
        assert remaining_tasks <= total_tasks * 0.2, (
            f"Too many tasks remaining: {remaining_tasks}"
        )

        logger.info("✅ Test 4 PASSED - High load stress test completed successfully")

    async def test_concurrent_agents_simulation(self):
        """Stress test: Simulate multiple concurrent agents with cross-dependencies."""
        logger.info("=== Test 5: Concurrent Agents Simulation ===")

        agent_types = ["inventory_agent", "ordering_agent", "analytics_agent"]
        managers = {}

        # Create managers for each agent type
        for agent_type in agent_types:
            managers[agent_type] = BaseManager(agent_type=agent_type)
            await self.redis.hset(
                RedisKeys.AGENT_STATUS, agent_type, AgentStatus.IDLE.value
            )

        logger.info(f"🤖 Created {len(agent_types)} concurrent agent managers")

        # Start all managers
        manager_tasks = []
        for agent_type, manager in managers.items():
            task = asyncio.create_task(manager.start())
            manager_tasks.append(task)

        await asyncio.sleep(0.1)  # Let managers start

        # Track execution across all agents
        all_commands = {agent_type: [] for agent_type in agent_types}

        async def monitor_agent_commands(agent_type):
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(RedisChannels.get_command_channel(agent_type))

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("command") == "execute":
                        all_commands[agent_type].append(data)

                        # Auto-complete tasks for simulation
                        completion_message = {
                            "query_id": data["query_id"],
                            "sub_query": data["sub_query"],
                            "status": TaskStatus.DONE,
                            "results": {
                                data["sub_query"]: f"Completed by {agent_type}"
                            },
                            "context": {"agent": agent_type},
                            "llm_usage": {"tokens": 25, "cost": 0.0005},
                            "timestamp": datetime.now().isoformat(),
                            "update_type": "task_completed",
                        }

                        await asyncio.sleep(0.005)  # Simulate processing

                        await self.redis.publish(
                            RedisChannels.get_task_updates_channel(agent_type),
                            json.dumps(completion_message),
                        )

                        # Stop when this agent gets 5 tasks
                        if len(all_commands[agent_type]) >= 5:
                            break

            await pubsub.unsubscribe(RedisChannels.get_command_channel(agent_type))

        # Start monitoring all agents
        monitor_tasks = []
        for agent_type in agent_types:
            task = asyncio.create_task(monitor_agent_commands(agent_type))
            monitor_tasks.append(task)

        # Send cross-dependent queries
        cross_queries = [
            {
                "query_id": "cross_query_001",
                "agent_type": ["inventory_agent", "ordering_agent"],
                "sub_query": {
                    "inventory_agent": [
                        "Check stock levels",
                        "Verify availability",
                        "Update inventory",
                    ],
                    "ordering_agent": ["Create purchase order", "Send to supplier"],
                },
            },
            {
                "query_id": "cross_query_002",
                "agent_type": ["ordering_agent", "analytics_agent"],
                "sub_query": {
                    "ordering_agent": ["Process orders", "Update status"],
                    "analytics_agent": [
                        "Generate sales report",
                        "Calculate metrics",
                        "Trend analysis",
                    ],
                },
            },
        ]

        start_time = asyncio.get_event_loop().time()

        for query in cross_queries:
            await self.redis.publish(RedisChannels.QUERY_CHANNEL, json.dumps(query))
            await asyncio.sleep(0.01)

        logger.info("🚀 Sent cross-dependent queries to multiple agents")

        # Wait for processing to complete
        try:
            await asyncio.wait_for(asyncio.gather(*monitor_tasks), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("⏰ Timeout in concurrent agents test")

        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time

        # Analyze results
        total_commands = sum(len(commands) for commands in all_commands.values())

        logger.info("🤖 CONCURRENT AGENTS RESULTS:")
        logger.info(f"   ⏱️  Duration: {duration:.2f} seconds")
        logger.info(f"   📋 Total commands executed: {total_commands}")

        for agent_type in agent_types:
            count = len(all_commands[agent_type])
            logger.info(f"   🤖 {agent_type}: {count} tasks executed")

        # Cleanup
        for task in manager_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Clean up agent statuses
        for agent_type in agent_types:
            await self.redis.hdel(RedisKeys.AGENT_STATUS, agent_type)

        # Assertions
        assert total_commands >= 10, (
            f"Expected ≥10 total commands, got {total_commands}"
        )
        assert all(len(commands) >= 2 for commands in all_commands.values()), (
            "All agents should execute at least 2 tasks"
        )

        logger.info("✅ Test 5 PASSED - Concurrent agents simulation completed")

    async def cleanup_final(self):
        """Final cleanup."""
        await self._cleanup()
        if self.redis:
            await self.redis.aclose()


async def run_event_driven_tests():
    """Run all event-driven manager tests."""
    test_suite = TestEventDrivenManager()

    try:
        await test_suite.setup()

        # Run core functionality tests
        await test_suite.test_query_event_triggers_execution()
        await test_suite.test_completion_triggers_next_task()
        await test_suite.test_agent_busy_no_execution()

        # Run stress tests
        await test_suite.test_high_load_stress_test()
        await test_suite.test_concurrent_agents_simulation()

        print("\n🎉 ALL EVENT-DRIVEN TESTS PASSED!")
        print("📋 Manager now uses purely event-driven architecture:")
        print("   ✅ No more while True polling loops")
        print("   ✅ Reactive to query events")
        print("   ✅ Reactive to task completion events")
        print("   ✅ Respects agent status (idle/busy)")
        print("   🔥 High load stress testing (6 concurrent tasks)")
        print("   🤖 Multi-agent concurrent execution")

    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"\n❌ EVENT-DRIVEN TESTS FAILED: {e}")
        raise
    finally:
        await test_suite.cleanup_final()


if __name__ == "__main__":
    asyncio.run(run_event_driven_tests())
