import logging

from src.typing import BaseAgentResponse

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
            **kwargs,
        )

    async def initialize_prompt(self):
        await super().initialize_prompt(tools_example=TOOLS_EXAMPLE)

    async def process(self, request):
        try:
            if not self.prompt:
                raise RuntimeError("Agent not properly initialized")

            tool_calls_result = await self._parse_and_execute_tools(request.query)

            import json

            result_str = (
                json.dumps(tool_calls_result)
                if isinstance(tool_calls_result, dict)
                else str(tool_calls_result)
            )

            return BaseAgentResponse(
                query_id=request.query_id,
                result=result_str,
                context={"query": request.query, "agent_type": self.agent_type},
            )

        except Exception as e:
            import json

            error_result = {"error": f"Processing failed: {str(e)}"}
            return BaseAgentResponse(
                query_id=request.query_id,
                result=json.dumps(error_result),
                context={"query": request.query, "agent_type": self.agent_type},
            )

    async def _parse_and_execute_tools(self, query: str) -> dict:
        query_lower = query.lower()

        if "check stock" in query_lower or "stock level" in query_lower:
            product_id = self._extract_product_id(query)
            if product_id:
                try:
                    result = await self.call_mcp_tool(
                        "check_stock", {"product_id": product_id}
                    )
                    return {
                        "tool_calls": [
                            {
                                "tool_name": "check_stock",
                                "parameters": {"product_id": product_id},
                                "result": result,
                            }
                        ],
                        "execution_status": "success",
                    }
                except Exception as e:
                    return {
                        "tool_calls": [
                            {
                                "tool_name": "check_stock",
                                "parameters": {"product_id": product_id},
                                "error": str(e),
                            }
                        ],
                        "execution_status": "failed",
                    }
            else:
                return {"error": "Could not extract product ID from query"}

        elif "update stock" in query_lower or "restock" in query_lower:
            return {"error": "Stock update not implemented yet"}

        else:
            return {"error": "Unknown inventory operation"}

    def _extract_product_id(self, query: str) -> str:
        """Extract product ID from query using simple pattern matching"""
        import re

        patterns = [
            r"[A-Z]+-\d+",  # LAPTOP-001
            r"[A-Z]{3,}\d+",  # ABC123
            r"\b[A-Z0-9-]{5,}\b",  # General alphanumeric codes
        ]

        for pattern in patterns:
            match = re.search(pattern, query.upper())
            if match:
                return match.group()

        return None
