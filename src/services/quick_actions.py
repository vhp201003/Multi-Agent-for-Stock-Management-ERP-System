import json
import logging
from string import Template
from typing import Optional

from src.communication.llm import get_groq_client
from src.communication.redis import get_async_redis_connection
from src.services.registry import get_all_agents
from src.typing.redis import RedisKeys
from src.typing.schema import QuickActionsSchema
from src.utils.converstation import load_or_create_conversation

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = Template("""You are a smart AI assistant that predicts the next logical actions a user might want to take in a Multi-Agent ERP System for Stock Management.

Your task is to analyze the conversation context and generate exactly 3 contextual quick action suggestions.

AVAILABLE AGENT TOOLS:
$agent_tools

CORE PRINCIPLES:
1. **Tool-Aware**: ONLY suggest actions possible with the available agent tools above
2. **Context-Driven**: Base suggestions on conversation summary and recent queries
3. **Workflow-Oriented**: Move the workflow forward with actionable next steps
4. **Parameter-Rich**: Pre-fill all relevant parameters (SKUs, Order IDs, quantities, dates)
5. **Language-Aware**: Match the language of the user's recent messages

OUTPUT FORMAT:
You must return a JSON object with this exact structure:
{
  "suggestions": [
    "First action suggestion (< 80 chars)",
    "Second action suggestion (< 80 chars)",
    "Third action suggestion (< 80 chars)"
  ]
}

FORMATTING RULES:
- The JSON must have a "suggestions" field containing an array of exactly 3 strings
- Keep each suggestion under 80 characters
- Use natural, conversational language
- Pre-fill ALL relevant parameters extracted from conversation
- Match the language (Vietnamese/English) based on user's recent messages

EXAMPLES:

English conversation:
Summary: "User checking inventory levels"
Recent: "What's the stock level for SKU-A001?" → "SKU-A001 has 150 units"
Output: {
  "suggestions": [
    "Get reorder suggestions for SKU-A001",
    "Create purchase order for SKU-A001",
    "Check stock levels for related products"
  ]
}

Vietnamese conversation:
Summary: "Người dùng kiểm tra tồn kho"
Recent: "Tồn kho SKU-A001 là bao nhiêu?" → "SKU-A001 có 150 đơn vị"
Output: {
  "suggestions": [
    "Lấy đề xuất đặt hàng lại cho SKU-A001",
    "Tạo đơn đặt hàng cho SKU-A001",
    "Kiểm tra tồn kho sản phẩm liên quan"
  ]
}""")


USER_PROMPT_TEMPLATE = Template("""CONVERSATION SUMMARY:
$summary

RECENT CONVERSATION:
$recent_messages

Generate 3 contextual quick action suggestions based on the above context.""")


def get_system_prompt(agent_tools: dict) -> str:
    """Generate system prompt with agent tools for prompt caching.

    Args:
        agent_tools: Available agent tools from registry

    Returns:
        System prompt with embedded agent tools
    """
    tools_text = []
    for agent_name, agent_info in agent_tools.items():
        tools_list = [tool["name"] for tool in agent_info.get("tools", [])]
        if tools_list:
            tools_text.append(f"- {agent_name}: {', '.join(tools_list)}")

    agent_tools_text = "\n".join(tools_text) if tools_text else "No tools available"

    return SYSTEM_PROMPT_TEMPLATE.substitute(agent_tools=agent_tools_text)


def get_user_prompt(recent_messages: list[dict], summary: Optional[str]) -> str:
    """Format conversation context into user prompt.

    Args:
        recent_messages: Last 4-6 messages (to extract last 2 user queries)
        summary: Conversation summary from AI

    Returns:
        Formatted user prompt string
    """
    # Extract last 2 user queries + responses
    user_messages = [msg for msg in recent_messages if msg["role"] == "user"]
    last_user_queries = user_messages[-2:] if len(user_messages) >= 2 else user_messages

    # Format recent conversation
    recent_conversation = []
    for user_msg in last_user_queries:
        user_idx = recent_messages.index(user_msg)
        recent_conversation.append(f"USER: {user_msg['content']}")

        # Add assistant response if exists
        if user_idx + 1 < len(recent_messages):
            assistant_msg = recent_messages[user_idx + 1]
            if assistant_msg["role"] == "assistant":
                content = assistant_msg["content"]
                if len(content) > 300:
                    content = content[:300] + "..."
                recent_conversation.append(f"ASSISTANT: {content}")

    recent_messages_text = "\n".join(recent_conversation)
    summary_text = summary if summary else "No summary available yet"

    return USER_PROMPT_TEMPLATE.substitute(
        summary=summary_text,
        recent_messages=recent_messages_text,
    )


async def generate_quick_actions(
    conversation_id: str,
) -> Optional[list[str]]:
    """Generate quick action suggestions based on conversation context.

    Args:
        redis_client: Redis client for conversation storage
        llm_client: LLM client for generating suggestions
        conversation_id: Conversation ID to analyze

    Returns:
        List of 3 quick action suggestions, or None if generation fails
    """
    try:
        redis_client = get_async_redis_connection().client
        llm_client = get_groq_client().get_client()
        conversation = await load_or_create_conversation(redis_client, conversation_id)

        # Get recent messages (last 6 to extract last 2 user queries + responses)
        recent_messages = conversation.get_recent_messages(limit=6)

        if not recent_messages or len(recent_messages) < 2:
            return None

        # Get available agent tools from registry (for system prompt caching)
        agent_tools = get_all_agents()

        # Generate prompts
        system_prompt = get_system_prompt(agent_tools)
        user_prompt = get_user_prompt(recent_messages, conversation.summary)

        response = await llm_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": QuickActionsSchema.__name__,
                    "schema": QuickActionsSchema.model_json_schema(),
                },
            },
        )

        result = response.choices[0].message.content.strip()
        quick_actions_data = QuickActionsSchema.model_validate_json(result)
        suggestions = quick_actions_data.suggestions

        # Update conversation with quick actions
        conversation.update_quick_actions(suggestions)
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        await redis_client.json().set(
            conversation_key,
            "$",
            json.loads(conversation.model_dump_json()),
        )

        logger.info(
            f"Generated {len(suggestions)} quick actions for conversation {conversation_id}"
        )
        return suggestions

    except Exception as e:
        logger.error(f"Failed to generate quick actions for {conversation_id}: {e}")
        return None
