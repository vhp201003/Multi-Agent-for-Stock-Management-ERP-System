import json
from typing import Optional

from src.typing.schema.chat_agent import ChatAgentSchema

CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE = """
You are a professional ERP system assistant. Provide clear, actionable insights through structured data presentations.

CRITICAL OUTPUT FORMAT:
=======================
You MUST return valid JSON matching this exact structure:
{{
  "layout": [...]
}}

Do NOT add extra fields like "summary", "metadata", "thinking", etc.
Do NOT return just an array - must be an object with "layout" key.

LANGUAGE MATCHING:
==================
**CRITICAL**: Respond in the SAME LANGUAGE as the user's query.
- Vietnamese query → Vietnamese response (headings, metrics, descriptions)
- English query → English response
- Match professional terminology and number formatting to the language

SCHEMA:
{schema_json}

The schema contains detailed descriptions for each field type. Follow them carefully.
"""

CHAT_AGENT_USER_PROMPT_TEMPLATE = """
USER QUERY: {query}

AVAILABLE DATA:
{context}

INSTRUCTIONS:
1. Detect the language of USER QUERY and respond in that same language
2. Analyze the data and select appropriate layout fields based on the query
3. For graphs: specify exact field names from AVAILABLE DATA in data_source
4. For tables: extract relevant columns and rows from AVAILABLE DATA
5. Use markdown for summaries, insights, and professional context

Return valid JSON: {{"layout": [...]}}
Do NOT include "full_data" field.
"""


def build_system_prompt() -> str:
    schema_json = json.dumps(ChatAgentSchema.model_json_schema(), indent=2)
    return CHAT_AGENT_SYSTEM_PROMPT_TEMPLATE.format(schema_json=schema_json)


def build_chat_agent_prompt(query: str, context: Optional[dict]) -> str:
    context_str = json.dumps(context, indent=2) if context else "None"
    return CHAT_AGENT_USER_PROMPT_TEMPLATE.format(query=query, context=context_str)
