"""Test WorkerAgent prompt initialization with MCP client."""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agents.worker_agent import WorkerAgent

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_worker_agent_prompt():
    """Test WorkerAgent prompt initialization from MCP server."""
    logger.info("=" * 80)
    logger.info("Testing WorkerAgent Prompt Initialization")
    logger.info("=" * 80)

    # Create InventoryAgent
    logger.info("Creating InventoryAgent...")
    inventory_agent = WorkerAgent(
        agent_type="InventoryAgent",
        agent_description="Manages inventory operations including stock checks and updates",
        mcp_server_url="http://localhost:8001/mcp",  # Using test MCP server
        redis_host="localhost",
        redis_port=6379,
    )

    try:
        # Initialize prompt only (without starting full agent)
        logger.info("Initializing prompt from MCP server...")
        await inventory_agent.initialize_prompt()

        # Print the generated prompt
        logger.info("=" * 80)
        logger.info("Generated Prompt:")
        logger.info("=" * 80)
        print("\n" + inventory_agent.prompt + "\n")
        logger.info("=" * 80)

        # Verify prompt is not None
        assert inventory_agent.prompt is not None, "Prompt should not be None"
        assert "InventoryAgent" in inventory_agent.prompt, (
            "Prompt should contain agent name"
        )
        assert "Available Tools" in inventory_agent.prompt, (
            "Prompt should contain tools section"
        )
        assert "Available Resources" in inventory_agent.prompt, (
            "Prompt should contain resources section"
        )

        logger.info("✅ Prompt initialization successful!")
        logger.info(f"Prompt length: {len(inventory_agent.prompt)} characters")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise
    finally:
        # Cleanup MCP client first to avoid asyncio errors
        if hasattr(inventory_agent, "mcp_client") and inventory_agent.mcp_client:
            try:
                await inventory_agent.mcp_client.close()
            except Exception as e:
                logger.warning(f"Error closing MCP client: {e}")

        # Then cleanup Redis
        await inventory_agent.redis.aclose()


async def test_worker_agent_full_start():
    """Test WorkerAgent full start (with prompt initialization)."""
    logger.info("=" * 80)
    logger.info("Testing WorkerAgent Full Start")
    logger.info("=" * 80)

    # Create agent
    inventory_agent = WorkerAgent(
        name="InventoryAgent",
        agent_description="Manages inventory operations including stock checks and updates",
        mcp_server_url="http://localhost:8001/mcp",
        redis_host="localhost",
        redis_port=6379,
    )

    try:
        # Start agent in background (it will run listen_channels forever)
        logger.info("Starting agent (background task)...")
        start_task = asyncio.create_task(inventory_agent.start())

        # Wait a bit for initialization
        await asyncio.sleep(2)

        # Check prompt is initialized
        logger.info("Checking prompt initialization...")
        assert inventory_agent.prompt is not None, "Prompt should be initialized"
        logger.info("✅ Agent started successfully with prompt initialized!")

        # Print prompt
        logger.info("=" * 80)
        logger.info("Agent Prompt:")
        logger.info("=" * 80)
        print("\n" + inventory_agent.prompt + "\n")
        logger.info("=" * 80)

        # Cancel background task
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            logger.info("Agent task cancelled")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise
    finally:
        # Cleanup MCP client first to avoid asyncio errors
        if hasattr(inventory_agent, "mcp_client") and inventory_agent.mcp_client:
            try:
                await inventory_agent.mcp_client.close()
            except Exception as e:
                logger.warning(f"Error closing MCP client: {e}")

        # Then cleanup Redis
        await inventory_agent.redis.aclose()


async def main():
    """Run all tests."""
    logger.info("Starting WorkerAgent Prompt Tests")
    logger.info("Make sure MCP test server is running on http://localhost:8001/mcp")
    logger.info("")

    try:
        # Test 1: Prompt initialization only
        await test_worker_agent_prompt()
        logger.info("")

        # Test 2: Full agent start
        # await test_worker_agent_full_start()

    except Exception as e:
        logger.error(f"Tests failed: {e}")
        return 1

    logger.info("")
    logger.info("=" * 80)
    logger.info("✅ All tests passed!")
    logger.info("=" * 80)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
