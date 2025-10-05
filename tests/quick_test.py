#!/usr/bin/env python3

"""
Quick test of the comprehensive multi-agent flow demo
"""

import asyncio
import sys

# Add the project root to Python path
sys.path.insert(
    0,
    "/home/fuc/Documents/DataWorkSpace/KLTN/Multi-Agent-for-Stock-Management-ERP-System",
)

try:
    from tests.test_complete_multi_agent_flow import MultiAgentSystemDemo

    print("✅ Successfully imported MultiAgentSystemDemo")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)


async def quick_test():
    """Quick test of the demo system"""
    print("🚀 Starting Multi-Agent Demo...")

    demo = MultiAgentSystemDemo()

    # Test just the initialization
    print(f"📝 Query ID: {demo.query_id}")
    print("✅ Demo instance created successfully")

    # Test Redis mock
    await demo.redis.set("test_key", "test_value")
    value = await demo.redis.get("test_key")
    print(f"📡 Redis mock test: {value}")

    print("🎉 Basic tests passed!")


if __name__ == "__main__":
    asyncio.run(quick_test())
