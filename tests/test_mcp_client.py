import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
from src.utils.extract_schema import extract_groq_tools

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")
logger = logging.getLogger(__name__)


async def run_client():
    """Fetch MCP tools and convert to Groq format."""
    server_url = "http://0.0.0.0:8011/mcp"

    try:
        async with streamablehttp_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                logger.info("Initializing MCP session...")
                await session.initialize()

                logger.info("Fetching tools from MCP server...")
                tools_result = await session.list_tools()

                if not tools_result.tools:
                    logger.warning("No tools available")
                    return

                mcp_tools_dicts = [tool.model_dump() for tool in tools_result.tools]
                groq_tools = extract_groq_tools(mcp_tools_dicts)

                logger.info(f"Converted {len(groq_tools)} tools to Groq format\n")

                print(json.dumps(groq_tools, indent=2, ensure_ascii=False))

    except ConnectionError as e:
        logger.error(f"Connection failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.critical(f"Fatal: {e}")
        exit(1)
