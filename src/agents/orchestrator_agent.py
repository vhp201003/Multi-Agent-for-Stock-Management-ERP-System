from .base_agent import BaseAgent
from src.typing.request import OrchestratorRequest
from src.typing.response import OrchestratorResponse

class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str, llm_api_key: str):
        super().__init__(name, llm_api_key=llm_api_key)

    async def process(self, request: OrchestratorRequest) -> OrchestratorResponse:
        try:
            if not request.query:
                raise ValueError("Query cannot be empty")
            
            messages = self.config.messages + [{"role": "user", "content": request.query}]
            
            response_content = await self._call_llm(messages)
            
            return OrchestratorResponse(
                query_id=request.query_id,
                response={"text": response_content},
            )
        except Exception as e:
            return OrchestratorResponse(
                query_id=request.query_id,
                response={"error": str(e)},
                error=str(e)
            )