import logging

from config.prompts import build_orchestrator_prompt

from src.typing.request import OrchestratorRequest
from src.typing.response import OrchestratorResponse
from src.typing.schema import OrchestratorSchema

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "OrchestratorAgent"):
        super().__init__(name)
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)

    async def process(self, request: OrchestratorRequest) -> OrchestratorResponse:
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
