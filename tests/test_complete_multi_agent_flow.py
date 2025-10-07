"""
Comprehensive Multi-Agent System Flow Demo

Demonstrates the complete end-to-end flow:
User Query → Orchestrator → Managers → Agents → ChatAgent → User Response

This test simulates the entire multi-agent workflow without requiring
actual Redis, LLM APIs, or MCP servers.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from redis.commands.json.path import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockRedis:
    """Mock Redis client for testing."""

    def __init__(self):
        self.data = {}
        self.channels = {}
        self.subscribers = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value: str):
        self.data[key] = value

    async def publish(self, channel: str, message: str):
        logger.info(f"📡 REDIS PUBLISH [{channel}]: {message[:100]}...")
        if channel in self.subscribers:
            for callback in self.subscribers[channel]:
                await callback(channel, message)

    def pubsub(self):
        return MockPubSub(self)

    def add_subscriber(self, channel: str, callback):
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        self.subscribers[channel].append(callback)


class MockPubSub:
    """Mock Redis PubSub for testing."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.subscribed_channels = []

    async def subscribe(self, *channels):
        self.subscribed_channels.extend(channels)
        for channel in channels:
            self.redis.add_subscriber(channel, self.message_callback)

    async def psubscribe(self, *patterns):
        # For pattern subscriptions
        for pattern in patterns:
            if "*" in pattern:
                self.redis.add_subscriber(pattern, self.message_callback)

    async def message_callback(self, channel, message):
        # This would be called when messages are published
        pass

    async def listen(self):
        # Mock async generator for listening
        yield {"type": "subscribe", "channel": "test"}
        # In real implementation, this would yield messages


class MockLLM:
    """Mock LLM for testing different agent responses."""

    def __init__(self):
        self.responses = {}

    def set_response(self, agent_type: str, response: Any):
        self.responses[agent_type] = response

    async def chat_completions_create(self, messages, **kwargs):
        # Determine agent type from messages
        system_msg = messages[0].get("content", "") if messages else ""

        if "orchestrator" in system_msg.lower():
            return self._create_orchestrator_response()
        elif "layout generator" in system_msg.lower():
            return self._create_chat_agent_response()
        else:
            return self._create_worker_response()

    def _create_orchestrator_response(self):
        response_data = {
            "agents_needed": ["inventory", "forecasting", "ordering"],
            "sub_queries": [
                "Check current stock level for Product A",
                "Forecast 3-month demand for Product A",
                "Create purchase order if shortage detected",
            ],
            "dependencies": [["inventory", "ordering"], ["forecasting", "ordering"]],
        }

        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(response_data)))]
        )

    def _create_chat_agent_response(self):
        layout_data = {
            "layout": [
                {
                    "field_type": "section_break",
                    "title": "Product A Analysis Results",
                    "description": "Complete inventory and procurement analysis",
                },
                {
                    "field_type": "markdown",
                    "content": "## Executive Summary\n\n**Current Stock**: 150 units  \n**Forecasted Demand**: 400 units (3 months)  \n**Recommended Action**: Purchase 250 additional units  \n**Status**: ✅ Purchase order PO-001 created",
                },
                {"field_type": "column_break"},
                {
                    "field_type": "graph",
                    "graph_type": "barchart",
                    "title": "Stock Analysis",
                    "data": {
                        "labels": [
                            "Current Stock",
                            "3-Month Demand",
                            "Recommended Order",
                        ],
                        "datasets": [{"data": [150, 400, 250], "label": "Units"}],
                    },
                },
                {
                    "field_type": "table",
                    "title": "Action Summary",
                    "data": {
                        "headers": ["Task", "Agent", "Result", "Status"],
                        "rows": [
                            [
                                "Stock Check",
                                "Inventory",
                                "150 units available",
                                "✅ Complete",
                            ],
                            [
                                "Demand Forecast",
                                "Forecasting",
                                "400 units needed",
                                "✅ Complete",
                            ],
                            [
                                "Purchase Order",
                                "Ordering",
                                "PO-001 for 250 units",
                                "✅ Created",
                            ],
                        ],
                    },
                },
            ]
        }

        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(layout_data)))]
        )

    def _create_worker_response(self):
        return MagicMock(
            choices=[
                MagicMock(message=MagicMock(content="Task completed successfully"))
            ]
        )


class MultiAgentSystemDemo:
    """Complete multi-agent system flow demonstration."""

    def __init__(self):
        self.redis = MockRedis()
        self.llm = MockLLM()
        self.query_id = f"demo_{datetime.now().strftime('%H%M%S')}"
        self.shared_data = {}

    async def run_complete_demo(self):
        """Run the complete multi-agent flow demonstration."""

        print("🚀 MULTI-AGENT SYSTEM FLOW DEMO")
        print("=" * 80)
        print(f"Query ID: {self.query_id}")
        print()

        # Step 1: User Query Input
        await self._step_1_user_query()

        # Step 2: Orchestrator Processing
        await self._step_2_orchestrator()

        # Step 3: Manager Task Distribution
        await self._step_3_managers()

        # Step 4: Agent Execution (Parallel)
        await self._step_4_agents()

        # Step 5: Dependency Resolution & Final Agent
        await self._step_5_dependency_resolution()

        # Step 6: All Tasks Completion Detection
        await self._step_6_completion_detection()

        # Step 7: ChatAgent Activation
        await self._step_7_chat_agent()

        # Step 8: Final Response
        await self._step_8_final_response()

        print("\n🎉 DEMO COMPLETE - Full Multi-Agent Flow Demonstrated!")
        return self.shared_data

    async def _step_1_user_query(self):
        """Step 1: User submits query"""
        print("📝 STEP 1: USER QUERY INPUT")
        print("-" * 40)

        user_query = "Check inventory for Product A, forecast demand, and create purchase order if needed"
        print(f"👤 User Query: {user_query}")

        # Store initial request
        request_data = {
            "query_id": self.query_id,
            "query": user_query,
            "timestamp": datetime.now().isoformat(),
            "status": "received",
        }

        await self.redis.set(f"request:{self.query_id}", json.dumps(request_data))
        print(f"✅ Query received and assigned ID: {self.query_id}")
        print()

    async def _step_2_orchestrator(self):
        """Step 2: Orchestrator decomposes query"""
        print("🧠 STEP 2: ORCHESTRATOR PROCESSING")
        print("-" * 40)

        print("🤖 OrchestratorAgent analyzing query...")

        # Simulate orchestrator LLM call
        orchestrator_response = {
            "agents_needed": ["inventory", "forecasting", "ordering"],
            "sub_queries": [
                "Check current stock level for Product A",
                "Forecast 3-month demand for Product A",
                "Create purchase order if shortage detected",
            ],
            "dependencies": [["inventory", "ordering"], ["forecasting", "ordering"]],
        }

        print(f"📊 Agents needed: {orchestrator_response['agents_needed']}")
        print(f"📋 Sub-queries generated: {len(orchestrator_response['sub_queries'])}")
        print(f"🔗 Dependencies: {orchestrator_response['dependencies']}")

        # Create shared data
        self.shared_data = {
            "original_query": "Check inventory for Product A, forecast demand, and create purchase order if needed",
            "agents_needed": orchestrator_response["agents_needed"],
            "agents_done": [],
            "sub_queries": {
                "inventory": ["Check current stock level for Product A"],
                "forecasting": ["Forecast 3-month demand for Product A"],
                "ordering": ["Create purchase order if shortage detected"],
            },
            "results": {},
            "context": {},
            "status": "processing",
            "graph": {
                "nodes": {
                    "inventory": {
                        "sub_queries": [
                            {
                                "query": "Check current stock level for Product A",
                                "status": "pending",
                            }
                        ]
                    },
                    "forecasting": {
                        "sub_queries": [
                            {
                                "query": "Forecast 3-month demand for Product A",
                                "status": "pending",
                            }
                        ]
                    },
                    "ordering": {
                        "sub_queries": [
                            {
                                "query": "Create purchase order if shortage detected",
                                "status": "pending",
                            }
                        ]
                    },
                },
                "edges": [["inventory", "ordering"], ["forecasting", "ordering"]],
            },
        }

        # Use Redis JSON to set shared data
        from redis.commands.json.path import Path

        await self.redis.json().set(
            f"agent:shared_data:{self.query_id}", Path.root_path(), self.shared_data
        )

        # Publish to managers
        query_task = {
            "query_id": self.query_id,
            "agent_type": orchestrator_response["agents_needed"],
            "sub_query": {
                "inventory": ["Check current stock level for Product A"],
                "forecasting": ["Forecast 3-month demand for Product A"],
                "ordering": ["Create purchase order if shortage detected"],
            },
            "dependencies": orchestrator_response["dependencies"],
        }

        await self.redis.publish("agent:query_channel", json.dumps(query_task))
        print("📤 Tasks published to managers")
        print()

    async def _step_3_managers(self):
        """Step 3: Managers handle task distribution"""
        print("📋 STEP 3: MANAGERS PROCESSING")
        print("-" * 40)

        # Simulate manager processing
        print("🔄 InventoryManager: Checking dependencies...")
        print("   → No dependencies for inventory task")
        print("   → Adding to agent:queue:inventory")

        print("🔄 ForecastingManager: Checking dependencies...")
        print("   → No dependencies for forecasting task")
        print("   → Adding to agent:queue:forecasting")

        print("🔄 OrderingManager: Checking dependencies...")
        print("   → Dependencies: [inventory, forecasting]")
        print("   → Adding to agent:pending_queue:ordering")

        # Simulate queue states
        await self.redis.set(
            "agent:queue:inventory",
            json.dumps(
                [
                    {
                        "query_id": self.query_id,
                        "query": "Check current stock level for Product A",
                    }
                ]
            ),
        )

        await self.redis.set(
            "agent:queue:forecasting",
            json.dumps(
                [
                    {
                        "query_id": self.query_id,
                        "query": "Forecast 3-month demand for Product A",
                    }
                ]
            ),
        )

        await self.redis.set(
            "agent:pending_queue:ordering",
            json.dumps(
                [
                    {
                        "query_id": self.query_id,
                        "query": "Create purchase order if shortage detected",
                    }
                ]
            ),
        )

        # Check agent status and dispatch
        print("\n🚀 Dispatching ready agents...")
        await self.redis.publish(
            "agent:command_channel:inventory",
            json.dumps(
                {
                    "agent_type": "inventory",
                    "command": "execute",
                    "query_id": self.query_id,
                }
            ),
        )

        await self.redis.publish(
            "agent:command_channel:forecasting",
            json.dumps(
                {
                    "agent_type": "forecasting",
                    "command": "execute",
                    "query_id": self.query_id,
                }
            ),
        )

        print("✅ Inventory and Forecasting agents dispatched")
        print("⏳ Ordering agent waiting for dependencies")
        print()

    async def _step_4_agents(self):
        """Step 4: Agents execute tasks in parallel"""
        print("🔧 STEP 4: AGENT EXECUTION")
        print("-" * 40)

        # Simulate parallel agent execution
        print("🏃‍♂️ InventoryAgent executing...")
        inventory_result = await self._simulate_inventory_agent()

        print("🏃‍♀️ ForecastingAgent executing...")
        forecasting_result = await self._simulate_forecasting_agent()

        # Update shared data with results
        self.shared_data["agents_done"] = ["inventory", "forecasting"]
        self.shared_data["results"] = {
            "inventory": inventory_result["results"],
            "forecasting": forecasting_result["results"],
        }
        self.shared_data["context"] = {
            "inventory": inventory_result["context"],
            "forecasting": forecasting_result["context"],
        }

        # Update graph status
        self.shared_data["graph"]["nodes"]["inventory"]["sub_queries"][0]["status"] = (
            "done"
        )
        self.shared_data["graph"]["nodes"]["forecasting"]["sub_queries"][0][
            "status"
        ] = "done"

        # Use Redis JSON to update shared data
        await self.redis.json().set(
            f"agent:shared_data:{self.query_id}", Path.root_path(), self.shared_data
        )

        # Publish completion updates
        await self.redis.publish(
            "agent:task_updates:inventory",
            json.dumps(
                {
                    "query_id": self.query_id,
                    "sub_query": "Check current stock level for Product A",
                    "status": "done",
                    "results": inventory_result["results"],
                    "context": inventory_result["context"],
                }
            ),
        )

        await self.redis.publish(
            "agent:task_updates:forecasting",
            json.dumps(
                {
                    "query_id": self.query_id,
                    "sub_query": "Forecast 3-month demand for Product A",
                    "status": "done",
                    "results": forecasting_result["results"],
                    "context": forecasting_result["context"],
                }
            ),
        )

        print("✅ Both agents completed successfully")
        print()

    async def _simulate_inventory_agent(self):
        """Simulate InventoryAgent execution"""
        print("   🔍 Connecting to inventory database...")
        await asyncio.sleep(0.1)  # Simulate processing time
        print("   📊 Querying stock levels...")
        await asyncio.sleep(0.1)
        print("   ✅ Stock check complete: 150 units available")

        return {
            "results": {
                "Check current stock level for Product A": "Current stock: 150 units in warehouse WH-001"
            },
            "context": {
                "Check current stock level for Product A": {
                    "stock_level": 150,
                    "warehouse": "WH-001",
                    "last_updated": "2025-10-05",
                }
            },
        }

    async def _simulate_forecasting_agent(self):
        """Simulate ForecastingAgent execution"""
        print("   📈 Loading historical data...")
        await asyncio.sleep(0.1)
        print("   🤖 Running ML forecasting model...")
        await asyncio.sleep(0.2)
        print("   ✅ Forecast complete: 400 units needed over 3 months")

        return {
            "results": {
                "Forecast 3-month demand for Product A": "Forecasted demand: 400 units over next 3 months (confidence: 85%)"
            },
            "context": {
                "Forecast 3-month demand for Product A": {
                    "demand": 400,
                    "confidence": 0.85,
                    "trend": "increasing",
                }
            },
        }

    async def _step_5_dependency_resolution(self):
        """Step 5: Resolve dependencies and execute final agent"""
        print("🔗 STEP 5: DEPENDENCY RESOLUTION")
        print("-" * 40)

        print("🔄 Managers checking dependency completion...")
        print("   ✅ inventory agent done")
        print("   ✅ forecasting agent done")
        print("   🚀 ordering dependencies satisfied!")

        print("📦 Moving ordering task from pending to active queue...")

        # Move from pending to active queue
        await self.redis.set(
            "agent:queue:ordering",
            json.dumps(
                [
                    {
                        "query_id": self.query_id,
                        "query": "Create purchase order if shortage detected",
                    }
                ]
            ),
        )

        await self.redis.set("agent:pending_queue:ordering", json.dumps([]))

        # Dispatch ordering agent
        await self.redis.publish(
            "agent:command_channel:ordering",
            json.dumps(
                {
                    "agent_type": "ordering",
                    "command": "execute",
                    "query_id": self.query_id,
                }
            ),
        )

        print("🚀 OrderingAgent dispatched")

        # Simulate ordering agent execution
        print("\n🏃‍♂️ OrderingAgent executing...")
        ordering_result = await self._simulate_ordering_agent()

        # Update shared data
        self.shared_data["agents_done"].append("ordering")
        self.shared_data["results"]["ordering"] = ordering_result["results"]
        self.shared_data["context"]["ordering"] = ordering_result["context"]
        self.shared_data["graph"]["nodes"]["ordering"]["sub_queries"][0]["status"] = (
            "done"
        )

        # Use Redis JSON to update shared data
        await self.redis.json().set(
            f"agent:shared_data:{self.query_id}", Path.root_path(), self.shared_data
        )

        # Publish completion
        await self.redis.publish(
            "agent:task_updates:ordering",
            json.dumps(
                {
                    "query_id": self.query_id,
                    "sub_query": "Create purchase order if shortage detected",
                    "status": "done",
                    "results": ordering_result["results"],
                    "context": ordering_result["context"],
                }
            ),
        )

        print("✅ OrderingAgent completed successfully")
        print()

    async def _simulate_ordering_agent(self):
        """Simulate OrderingAgent execution"""
        print("   📊 Analyzing stock vs demand...")
        print("   📊 Stock: 150, Demand: 400, Gap: 250 units")
        print("   📋 Creating purchase order...")
        await asyncio.sleep(0.1)
        print("   ✅ Purchase order PO-001 created for 250 units")

        return {
            "results": {
                "Create purchase order if shortage detected": "Purchase order PO-001 created for 250 units of Product A"
            },
            "context": {
                "Create purchase order if shortage detected": {
                    "order_id": "PO-001",
                    "quantity": 250,
                    "amount": 25000,
                    "supplier": "Supplier ABC",
                }
            },
        }

    async def _step_6_completion_detection(self):
        """Step 6: Detect all tasks completion"""
        print("✅ STEP 6: COMPLETION DETECTION")
        print("-" * 40)

        print("🔍 OrchestratorAgent checking completion status...")

        # Check if all tasks done
        all_done = True
        for agent_type, agent_node in self.shared_data["graph"]["nodes"].items():
            for sub_query in agent_node["sub_queries"]:
                if sub_query["status"] != "done":
                    all_done = False
                    break

        print(f"   📊 Agents completed: {len(self.shared_data['agents_done'])}/3")
        print(f"   🎯 All tasks done: {all_done}")

        if all_done:
            self.shared_data["status"] = "done"
            # Use Redis JSON to update shared data
            await self.redis.json().set(
                f"agent:shared_data:{self.query_id}", Path.root_path(), self.shared_data
            )
            print("✅ All tasks completed - triggering ChatAgent")

        print()

    async def _step_7_chat_agent(self):
        """Step 7: ChatAgent generates final response"""
        print("🎨 STEP 7: CHATAGENT ACTIVATION")
        print("-" * 40)

        print("🔄 OrchestratorAgent triggering ChatAgent...")

        # Create filtered context
        filtered_context = {
            "original_query": self.shared_data["original_query"],
            "agents_completed": self.shared_data["agents_done"],
            "key_results": {},
            "metrics": {},
        }

        # Filter results (truncate to 500 chars)
        for agent_type, results in self.shared_data["results"].items():
            filtered_context["key_results"][agent_type] = {}
            for sub_query, result in results.items():
                truncated = result[:500] + "..." if len(result) > 500 else result
                filtered_context["key_results"][agent_type][sub_query] = truncated

        # Extract metrics
        for agent_type, contexts in self.shared_data["context"].items():
            for sub_query, ctx in contexts.items():
                for key, value in ctx.items():
                    if isinstance(value, (int, float)):
                        filtered_context["metrics"][f"{agent_type}_{key}"] = value

        print(f"📊 Filtered context size: {len(json.dumps(filtered_context))} chars")
        print(f"🔢 Extracted metrics: {len(filtered_context['metrics'])}")

        # Publish to ChatAgent
        chat_message = {
            "command": "execute",
            "query_id": self.query_id,
            "sub_query": {
                "query": "Generate comprehensive response based on completed analysis",
                "context": filtered_context,
            },
        }

        await self.redis.publish(
            "agent:command_channel:chat_agent", json.dumps(chat_message)
        )
        print("📤 ChatAgent command published")

        # Simulate ChatAgent processing
        print("\n🤖 ChatAgent processing...")
        chat_response = await self._simulate_chat_agent(filtered_context)

        print("✅ ChatAgent generated structured layout response")
        print(f"📊 Layout fields: {len(chat_response['layout'])}")

        self.final_response = chat_response
        print()

    async def _simulate_chat_agent(self, filtered_context):
        """Simulate ChatAgent layout generation"""
        print("   🧠 Analyzing multi-agent results...")
        await asyncio.sleep(0.1)
        print("   🎨 Generating structured layout...")
        await asyncio.sleep(0.1)
        print("   📊 Creating visualizations...")
        await asyncio.sleep(0.1)

        return {
            "layout": [
                {
                    "field_type": "section_break",
                    "title": "Product A Analysis Results",
                    "description": "Complete inventory and procurement analysis",
                },
                {
                    "field_type": "markdown",
                    "content": "## Executive Summary\n\n**Current Stock**: 150 units  \n**Forecasted Demand**: 400 units (3 months)  \n**Recommended Action**: Purchase 250 additional units  \n**Status**: ✅ Purchase order PO-001 created",
                },
                {"field_type": "column_break"},
                {
                    "field_type": "graph",
                    "graph_type": "barchart",
                    "title": "Stock vs Demand Analysis",
                    "data": {
                        "labels": [
                            "Current Stock",
                            "3-Month Demand",
                            "Recommended Order",
                        ],
                        "datasets": [{"data": [150, 400, 250], "label": "Units"}],
                    },
                },
                {
                    "field_type": "table",
                    "title": "Action Summary",
                    "data": {
                        "headers": ["Task", "Agent", "Result", "Status"],
                        "rows": [
                            [
                                "Stock Check",
                                "Inventory",
                                "150 units available",
                                "✅ Complete",
                            ],
                            [
                                "Demand Forecast",
                                "Forecasting",
                                "400 units needed",
                                "✅ Complete",
                            ],
                            [
                                "Purchase Order",
                                "Ordering",
                                "PO-001 for 250 units",
                                "✅ Created",
                            ],
                        ],
                    },
                },
            ]
        }

    async def _step_8_final_response(self):
        """Step 8: Deliver final response to user"""
        print("🎯 STEP 8: FINAL RESPONSE DELIVERY")
        print("-" * 40)

        print("📦 Packaging response for user...")

        response_summary = {
            "query_id": self.query_id,
            "status": "completed",
            "response_type": "structured_layout",
            "layout_fields": len(self.final_response["layout"]),
            "agents_involved": self.shared_data["agents_done"],
            "processing_time": "~2.5 seconds",
            "response": self.final_response,
        }

        print("✅ Response ready:")
        print(f"   📊 Layout fields: {response_summary['layout_fields']}")
        print(f"   🤖 Agents involved: {len(response_summary['agents_involved'])}")
        print(f"   ⏱️  Processing time: {response_summary['processing_time']}")

        print("\n📋 Layout Structure:")
        for i, field in enumerate(self.final_response["layout"], 1):
            print(f"   {i}. {field['field_type']}: {field.get('title', 'N/A')}")

        # Store final response
        await self.redis.set(f"response:{self.query_id}", json.dumps(response_summary))

        print("\n🎉 SUCCESS: User receives rich dashboard response!")
        return response_summary


async def main():
    """Run the complete multi-agent system demo."""

    demo = MultiAgentSystemDemo()

    try:
        result = await demo.run_complete_demo()

        print("\n" + "=" * 80)
        print("📊 DEMO STATISTICS")
        print("=" * 80)
        print(f"Total Agents: {len(result['agents_done'])}")
        print(
            f"Sub-queries processed: {sum(len(queries) for queries in result['sub_queries'].values())}"
        )
        print(f"Results generated: {len(result['results'])}")
        print(
            f"Metrics extracted: {len([k for contexts in result['context'].values() for ctx in contexts.values() for k, v in ctx.items() if isinstance(v, (int, float))])}"
        )
        print(f"Final response fields: {len(demo.final_response['layout'])}")

        print("\n🌟 MULTI-AGENT SYSTEM ADVANTAGES DEMONSTRATED:")
        print("✅ Parallel processing (inventory + forecasting)")
        print("✅ Dependency management (ordering waits for prerequisites)")
        print("✅ Context filtering (prevents prompt overload)")
        print("✅ Rich response generation (structured layouts)")
        print("✅ Business intelligence (cross-agent synthesis)")

        return result

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
