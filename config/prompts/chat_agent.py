import json
from typing import Optional

from src.typing.schema.chat_agent import ChatAgentSchema

CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE = """
You are a professional layout generator. Create clean layouts with 5 field types only.

RULES:
- Start with section_break for titles
- Use markdown for content and key numbers
- Use graph for data visualization when needed
- Use table for detailed data when needed
- Use column_break to organize layout

SCHEMA Layout:
{schema_json}

Use realistic sample data. YOU choose when graphs/tables add value.

YOU decide when to use graphs/tables. Keep it simple and focused.
Always return valid ChatAgentSchema JSON.
"""

CHAT_AGENT_USER_PROMPT_TEMPLATE = """
QUERY: {query}

## CONTEXT: 
{context}
"""


def build_system_prompt() -> str:
    schema_json = json.dumps(ChatAgentSchema.model_json_schema(), indent=2)
    return CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE.format(schema_json=schema_json)


def build_chat_agent_prompt(query: str, context: Optional[dict]) -> str:
    context_str = json.dumps(context) if context else "None"
    return CHAT_AGENT_USER_PROMPT_TEMPLATE.format(query=query, context=context_str)
