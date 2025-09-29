import traceback

from .base_agent import BaseAgent
from string import Template
import json
from src.typing.request import OrchestratorRequest
from src.typing.response import OrchestratorResponse
from config.prompts import ORCHESTRATOR_PROMPT
import os

class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "OrchestratorAgent"):
        super().__init__(name)
        self.agents_info = self.load_agents_info()
        self.prompt = self.load_prompt()
        
    def load_agents_info(self):
        agents_file = "config/agents.json"
        try:
            if os.path.exists(agents_file):
                with open(agents_file, "r") as f:
                    return json.load(f)
            else:
                return {}
        except json.JSONDecodeError as e:
            return {}
        
    def load_prompt(self):
        try:
            # Load agent descriptions
            agents_desc = []
            for name, info in self.agents_info.items():
                if name != "orchestrator":
                    desc = info.get("description", "")
                    caps = ", ".join(info.get("capabilities", []))
                    agents_desc.append(f"- {name}: {desc} (Capabilities: {caps})")
            agent_descriptions = "\n".join(agents_desc)
            
            # Get schema
            schema = OrchestratorResponse.model_json_schema()
            schema_str = json.dumps(schema, indent=2)
            # Thoát dấu ngoặc nhọn để tránh lỗi khi format sau này (nếu cần, nhưng Template không chạm vào)
            schema_str = schema_str.replace('{', '{{').replace('}', '}}')
            
            # Sử dụng Template thay vì format
            prompt_template = Template(ORCHESTRATOR_PROMPT)
            result = prompt_template.safe_substitute(
                agent_descriptions=agent_descriptions,
                schema=schema_str
            )
            return result
        except Exception as e:
            print(f"Error loading prompt: {e}")
            return ""  # Trả về chuỗi rỗng nếu lỗi

    async def process(self, request: OrchestratorRequest) -> OrchestratorResponse:
        try:
            if not request.query:
                raise ValueError("Query is required")
            messages = [{"role": "system", "content": self.prompt}] + [{"role": "user", "content": request.query}]
            
            response_content = await self._call_llm(messages, OrchestratorResponse)

            return response_content
        except Exception as e:
            traceback.print_exc()
            return OrchestratorResponse(
                agent_needed=[],
                sub_queries=[],
                dependencies=[]
            )