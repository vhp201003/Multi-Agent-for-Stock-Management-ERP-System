from .worker_agent import WorkerAgent
from src.typing.schema import ToolCallSchema
from src.typing.response import ToolCallResponse
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
    """Agent specialized in inventory management tasks."""

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
        from src.typing import BaseAgentResponse

        try:
            if not self.prompt:
                raise RuntimeError("Agent not properly initialized")

            # Build messages for LLM
            messages = [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": request.query},
            ]

            # Call LLM to get inventory action plan
            response_content = await self._call_llm(
                messages=messages,
                response_schema=ToolCallSchema,
                response_model=ToolCallResponse,
            )

            if not response_content:
                return BaseAgentResponse(
                    query_id=request.query_id,
                    result="No response from LLM",
                    error="llm_no_response",
                )

            # For now, return the LLM response directly
            # TODO: Parse LLM response to extract tool calls and execute them via MCP
            return BaseAgentResponse(
                query_id=request.query_id,
                result=str(response_content),
                context={"query": request.query, "agent_type": self.agent_type},
            )

        except Exception as e:
            return BaseAgentResponse(
                query_id=request.query_id,
                result="",
                error=f"Processing failed: {str(e)}",
                context={"query": request.query, "agent_type": self.agent_type},
            )
