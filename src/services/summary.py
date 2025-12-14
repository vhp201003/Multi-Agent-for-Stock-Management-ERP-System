import json
import logging
from string import Template
from typing import Optional

from src.communication.llm import get_groq_client
from src.communication.redis import get_async_redis_connection
from src.typing.redis import RedisKeys
from src.utils.converstation import load_or_create_conversation

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = """
You are a conversation summarizer. Your task is to create a concise but comprehensive summary that captures the user's intent and the conversation flow.

STRUCTURE YOUR SUMMARY AS FOLLOWS:

1. **User Intent**: What is the user trying to accomplish? What's their primary goal or problem?

2. **Key Topics & Context**:
   - Main topics discussed
   - Important context or constraints
   - User's pain points or concerns

3. **Decisions & Solutions**:
   - Important decisions made
   - Why they were chosen
   - Alternatives considered (if any)

4. **Agent Recommendations**:
   - Advice or solutions provided
   - Technical recommendations
   - Next steps suggested

5. **Action Items**:
   - What needs to be done
   - Who should do it (user or agent)
   - Priority or timeline (if mentioned)

GUIDELINES:
- Start with the user's PRIMARY INTENT in bold
- Keep the summary under 200 words
- Make it scannable with clear sections
- Prioritize user goals over technical details
- Highlight any blockers or constraints

Always return valid SummaryAgentSchema JSON with 'summary' field only.
"""


USER_PROMPT_TEMPLATE = Template("""Please analyze and summarize this conversation.
Focus especially on understanding what the user is trying to achieve and their main concerns:

CONVERSATION:
$messages_text

Remember to clearly identify the user's primary intent and structure your summary accordingly.""")


def get_user_prompt_for_summary(recent_messages: list[dict]) -> str:
    messages_text = "\n".join(
        [f"{msg['role'].upper()}: {msg['content']}" for msg in recent_messages]
    )

    user_prompt = USER_PROMPT_TEMPLATE.substitute(messages_text=messages_text)
    return user_prompt


async def summarize_conversation(
    conversation_id: str,
) -> Optional[str]:
    try:
        redis_client = get_async_redis_connection().client
        llm_client = get_groq_client()
        conversation = await load_or_create_conversation(redis_client, conversation_id)
        recent_messages = conversation.get_recent_messages(limit=10)

        if not recent_messages:
            logger.debug(f"No messages to summarize for {conversation_id}")
            return None

        user_prompt = get_user_prompt_for_summary(recent_messages)

        response = await llm_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
        )

        summary = response.choices[0].message.content.strip()

        conversation.update_summary(summary)
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        await redis_client.json().set(
            conversation_key,
            "$",
            json.loads(conversation.model_dump_json()),
        )

        return summary

    except Exception:
        return None
