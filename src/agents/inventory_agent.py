import logging

from .worker_agent import WorkerAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "inventory"
AGENT_DESCRIPTION = "Manages inventory operations including stock checks and updates"
MCP_SERVER_URL = "http://localhost:8001/mcp"
TOOLS_EXAMPLE = """
## Example for tools/resource usage: 

1. Tool call: Query "Check stock ABC123" → {"tool_calls": [{"tool_name": "check_stock", "parameters": {"product_id": "ABC123"}}]}
2. Combined: Query "Check ABC123 and show levels" → {"tool_calls": [...], "read_resource": ["stock://levels"]}
3. Error: Query "Predict sales" → {"error": "No forecasting tools available"}
"""


class InventoryAgent(WorkerAgent):
    def __init__(self, **kwargs):
        super().__init__(
            agent_type=AGENT_TYPE,
            agent_description=AGENT_DESCRIPTION,
            mcp_server_url=MCP_SERVER_URL,
            examples=TOOLS_EXAMPLE,
            **kwargs,
        )
