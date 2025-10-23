import json
from typing import Optional

from src.typing.schema.chat_agent import ChatAgentSchema

CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE = """
You are a professional layout generator. Create clean layouts with field types: section_break, markdown, graph, table, column_break.

IMPORTANT: Return ONLY a JSON object with a single 'layout' field containing an array of layout fields. Do NOT include any other fields like 'full_data'.

SCHEMA:
{schema_json}

Generate layout based on the provided context. Use graphs/tables when data supports visualization.
"""

CHAT_AGENT_USER_PROMPT_TEMPLATE = """
QUERY: {query}

## FILTERED CONTEXT (for layout generation): 
{context}
"""


def build_system_prompt() -> str:
    schema_json = json.dumps(ChatAgentSchema.model_json_schema(), indent=2)
    return CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE.format(schema_json=schema_json)


def build_chat_agent_prompt(query: str, context: Optional[dict]) -> str:
    context_str = json.dumps(context) if context else "None"
    return CHAT_AGENT_USER_PROMPT_TEMPLATE.format(query=query, context=context_str)
