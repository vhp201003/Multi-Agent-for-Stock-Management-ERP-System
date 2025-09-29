import asyncio
import json
import os
from typing import List, Dict, Any, Optional, Type
from groq import AsyncGroq
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

load_dotenv()

# Define Pydantic models
class BaseAgentResponse(BaseModel):
    query_id: str

class Query(BaseModel):
    agent_name: str
    sub_query: list[str]

class Dependency(BaseModel):
    agent_name: str
    dependencies: List[str]

class OrchestratorResponse(BaseAgentResponse):
    agent_needed: list[str]
    sub_queries: Query
    dependencies: Dependency

# Simple config
class AgentConfig:
    model: str = "openai/gpt-oss-20b"
    temperature: float = 0.7
    messages: List[Dict[str, str]] = [{"role": "system", "content": "You are a helpful assistant."}]

# BaseAgent class (simplified)
class BaseAgent:
    def __init__(self, name: str, prompt: str):
        self.name = name
        self.prompt = prompt
        self.config = AgentConfig()
        self.llm_api_key = os.environ.get("GROQ_API_KEY")
        self.llm = AsyncGroq(api_key=self.llm_api_key) if self.llm_api_key else None

    async def _call_llm(self, messages: List[Dict[str, str]], response_model: Optional[Type[BaseModel]] = None) -> Any:
        if not self.llm:
            raise ValueError("No Groq API key provided")
        try:
            response_format = None
            if response_model:
                schema = response_model.model_json_schema()
                response_format = {
                    "type": "json_schema", 
                    "json_schema": {
                        "name": "orchestrator_response", 
                        "schema": response_model.model_json_schema()
                        }
                }
            response = await self.llm.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                response_format=response_format
            )
            content = response.choices[0].message.content.strip()
            print(f"LLM response: {content}")
            if response_model:
                try:
                    data = json.loads(content)
                    return response_model.model_validate(data)  # Sử dụng model_validate như sample
                except (json.JSONDecodeError, ValidationError) as e:
                    print(f"LLM response parsing error: {e}")
                    return None
            else:
                return content
        except Exception as e:
            print(f"Groq API error: {e}")
            return "LLM error: Unable to generate response"

# OrchestratorAgent class
class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "Orchestrator"):
        prompt = """
    Analyze the query and return ONLY a JSON object with 
    'agent_needed': [list of agent names (e.g., ['sql', 'chat'])], 
    'sub_queries': {{'agent_name': 'sql', 'sub_query': ['sub query 1', 'sub query 2']}}, 
    'dependencies': {{'agent_name': 'sql', 'dependencies': ['chat']}}. 
    Do not include any extra text. Query: {query}"""
        super().__init__(name, prompt)

    async def process(self, query: str, query_id: str) -> OrchestratorResponse:
        try:
            messages = self.config.messages + [{"role": "user", "content": self.prompt.format(query=query)}]
            response_content = await self._call_llm(messages, OrchestratorResponse)
            
            if response_content is None:
                response_content = OrchestratorResponse(
                    query_id=query_id,
                    agent_needed=[],
                    sub_queries={"agent_name": "", "sub_query": []},
                    dependencies={"agent_name": "", "dependencies": []}
                )
            
            response_content.query_id = query_id
            return response_content
        except Exception as e:
            print(f"Error: {e}")
            return OrchestratorResponse(
                query_id=query_id,
                agent_needed=[],
                sub_queries={"agent_name": "", "sub_query": []},
                dependencies={"agent_name": "", "dependencies": []}
            )

# Test function
async def test_orchestrator():
    agent = OrchestratorAgent()
    query = "Check stock for P001 and summarize"
    query_id = "test_123"
    response = await agent.process(query, query_id)
    print(f"Response: {response}")
    print(f"Agent Needed: {response.agent_needed}")
    print(f"Sub Queries: {response.sub_queries}")
    print(f"Dependencies: {response.dependencies}")

if __name__ == "__main__":
    asyncio.run(test_orchestrator())