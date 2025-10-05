#!/usr/bin/env python3

"""
Run the complete multi-agent flow demonstration
"""

import asyncio
import sys

# Add the project root to Python path
sys.path.insert(
    0,
    "/home/fuc/Documents/DataWorkSpace/KLTN/Multi-Agent-for-Stock-Management-ERP-System",
)

from tests.test_complete_multi_agent_flow import main

if __name__ == "__main__":
    print("🎬 Running Complete Multi-Agent System Demo...")
    print("=" * 80)

    try:
        result = asyncio.run(main())
        print("\n✨ Demo completed successfully!")

    except KeyboardInterrupt:
        print("\n⏹️  Demo stopped by user")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        sys.exit(1)
