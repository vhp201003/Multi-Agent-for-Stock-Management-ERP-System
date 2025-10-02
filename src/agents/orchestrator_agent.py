import logging
from typing import Any, Dict, List

from config.prompts import build_orchestrator_prompt

from src.typing.request import OrchestratorRequest
from src.typing.response import OrchestratorResponse
from src.typing.schema import OrchestratorSchema

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "OrchestratorAgent"):
        """Initialize the OrchestratorAgent with a name and build the orchestrator prompt."""
        super().__init__(name)
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)

    async def get_pub_channels(self) -> List[str]:
        """Return list of channels this agent publishes to."""
        return ["agent:query_channel"]

    async def get_sub_channels(self) -> List[str]:
        """Return list of channels this agent subscribes to."""
        return ["agent:task_updates"]  # Sub all task updates, filter by agent

    async def handle_message(self, channel: str, message: Dict[str, Any]):
        """Handle task update messages and update shared data accordingly.

        Processes updates from worker agents, merges results into shared data,
        and checks if all tasks are complete to trigger next steps in the workflow.

        Args:
            channel (str): The channel the message was received on (e.g., agent:task_updates:AgentName).
            message (Dict[str, Any]): The update message containing query_id, results, context, etc.
        """
        if channel.startswith("agent:task_updates:"):
            agent_name = channel.split(":")[-1]
            query_id = message["query_id"]
            # Update shared data
            await self.update_shared_data(
                query_id,
                {
                    "agents_done": [agent_name],  # Append logic in update_shared_data
                    "results": {agent_name: message["results"]},
                    "context": {agent_name: message["context"]},
                },
            )
            # Check if all done, trigger next or finalize
            shared_key = f"agent:shared_data:{query_id}"
            current_data = await self.redis.get(shared_key)
            if current_data:
                # Placeholder: check graph for next tasks
                logger.info(f"Orchestrator updated for {query_id} from {agent_name}")

    async def process(self, request: OrchestratorRequest) -> OrchestratorResponse:
        """Process an orchestrator request by calling LLM and parsing the response.

        Sends the query to the LLM with the orchestrator prompt, parses the structured
        response to determine required agents, sub-queries, and dependencies.

        Args:
            request (OrchestratorRequest): The request containing the query and query_id.

        Returns:
            OrchestratorResponse: The parsed response with agent assignments and sub-queries,
            or an error response if processing fails.
        """
        try:
            if not request.query:
                raise ValueError("Query is required")
            messages = [{"role": "system", "content": self.prompt}] + [
                {"role": "user", "content": request.query}
            ]

            response_content = await self._call_llm(
                messages=messages,
                response_schema=OrchestratorSchema,
                response_model=OrchestratorResponse,
            )

            if response_content is None:
                return OrchestratorResponse(
                    query_id=request.query_id,
                    agent_needed=[],
                    sub_queries=[],
                    dependencies=[],
                    llm_usage=None,
                    llm_reasoning=None,
                    error="no_response_from_llm",
                )

            if hasattr(response_content, "agent_needed") and hasattr(
                response_content, "sub_queries"
            ):
                try:
                    response_content.query_id = request.query_id
                except Exception:
                    pass
                return response_content

            llm_usage = getattr(response_content, "llm_usage", None)
            llm_reasoning = getattr(response_content, "llm_reasoning", None)
            error = getattr(response_content, "error", "parse_error")

            return OrchestratorResponse(
                query_id=request.query_id,
                agent_needed=[],
                sub_queries=[],
                dependencies=[],
                llm_usage=llm_usage,
                llm_reasoning=llm_reasoning,
                error=error,
            )
        except Exception as e:
            logger.exception("OrchestratorAgent process failed: %s", e)
            return OrchestratorResponse(
                agent_needed=[], sub_queries=[], dependencies=[], error=str(e)
            )

    async def start(self):
        """Start the OrchestratorAgent by listening to channels."""
        await self.listen_channels()
