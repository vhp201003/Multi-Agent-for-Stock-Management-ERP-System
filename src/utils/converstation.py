import json
import logging
from datetime import datetime
from typing import Optional

from src.typing.redis import ConversationData, RedisKeys

logger = logging.getLogger(__name__)


async def load_or_create_conversation(
    redis_client, conversation_id: str, user_id: Optional[str] = None
) -> ConversationData:
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if conversation_data:
            return ConversationData(**conversation_data)
        else:
            logger.info(f"Creating new conversation {conversation_id}")
            new_conversation = ConversationData(
                conversation_id=conversation_id,
                messages=[],
                updated_at=datetime.now(),
                max_messages=50,
                user_id=user_id,
            )
            await redis_client.json().set(
                conversation_key,
                "$",
                json.loads(new_conversation.model_dump_json()),
            )
            logger.info(f"Created new conversation: {conversation_id}")
            return new_conversation

    except Exception as e:
        logger.warning(f"Error loading conversation, creating new: {e}")
        return ConversationData(
            conversation_id=conversation_id, messages=[], updated_at=datetime.now()
        )


async def save_conversation_message(
    redis_client,
    conversation_id: str,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
):
    try:
        logger.info(
            f"Loading/creating conversation {conversation_id} for saving message"
        )
        conversation = await load_or_create_conversation(redis_client, conversation_id)

        conversation.add_message(role=role, content=content, metadata=metadata)

        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        await redis_client.json().set(
            conversation_key,
            "$",
            json.loads(conversation.model_dump_json()),
        )

        logger.info(
            f"Saved {role} message to conversation {conversation_id} (total: {len(conversation.messages)} messages)"
        )

    except Exception as e:
        logger.error(f"Failed to save conversation message: {e}")


async def get_summary_conversation(redis_client, conversation_id: str) -> Optional[str]:
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if conversation_data is None:
            logger.debug(f"No conversation data found for {conversation_id}")
            return None

        conversation = ConversationData(**conversation_data)
        return conversation.summary

    except Exception as e:
        logger.error(f"Failed to get conversation summary for {conversation_id}: {e}")
        return None


async def summarize_conversation(
    redis_client,
    llm_client,
    conversation_id: str,
) -> Optional[str]:
    try:
        conversation = await load_or_create_conversation(redis_client, conversation_id)
        recent_messages = conversation.get_recent_messages(limit=10)

        if not recent_messages:
            logger.debug(f"No messages to summarize for {conversation_id}")
            return None

        # Format messages for LLM
        messages_text = "\n".join(
            [f"{msg['role'].upper()}: {msg['content']}" for msg in recent_messages]
        )

        # Build LLM request
        system_prompt = """
You are a conversation summarizer. Your task is to create a concise but comprehensive summary of the conversation.
Focus on:
- Key topics discussed
- Important decisions or conclusions
- Action items or next steps
- User's main concerns or questions
- Agent responses and recommendations

Keep the summary under 200 words and make it natural to read.
Always return valid SummaryAgentSchema JSON with 'summary' field only.
"""

        user_prompt = f"Summarize this conversation:\n\n{messages_text}"

        response = await llm_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
        )

        summary = response.choices[0].message.content.strip()

        # Update conversation with summary
        conversation.update_summary(summary)
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        await redis_client.json().set(
            conversation_key,
            "$",
            json.loads(conversation.model_dump_json()),
        )

        logger.info(f"Generated summary for conversation {conversation_id}")
        return summary

    except Exception as e:
        logger.error(f"Failed to summarize conversation {conversation_id}: {e}")
        return None


async def get_conversation(
    redis_client, conversation_id: str, user_id: Optional[str] = None
) -> Optional["Conversation"]:
    """Get a conversation by ID with proper model.

    Args:
        redis_client: Redis client instance
        conversation_id: Conversation ID to retrieve
        user_id: Optional user ID for permission check (if provided, validates ownership)

    Returns:
        Conversation object if found, None otherwise
    """
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if not conversation_data:
            logger.debug(f"Conversation {conversation_id} not found")
            return None

        if (
            user_id
            and conversation_data.get("user_id")
            and conversation_data.get("user_id") != user_id
        ):
            logger.warning(
                f"User {user_id} attempted to access conversation {conversation_id} (owner: {conversation_data.get('user_id')})"
            )
            return None

        conv_data = ConversationData(**conversation_data)
        return Conversation(
            id=conv_data.conversation_id,
            title=f"Conversation {conv_data.conversation_id[:8]}",  # Default title
            messages=conv_data.messages,
            created_at=conv_data.updated_at,  # Use updated_at as fallback
            updated_at=conv_data.updated_at,
        )

    except Exception as e:
        logger.error(f"Failed to get conversation {conversation_id}: {e}")
        return None


async def list_conversations(
    redis_client, user_id: str, limit: int = 50, offset: int = 0
) -> list["Conversation"]:
    """List all conversations with pagination."""
    try:
        pattern = "conversation:*"
        conversations = []

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match=pattern, count=100
            )

            for key in keys:
                try:
                    conv_data_raw = await redis_client.json().get(key)
                    if conv_data_raw:
                        conv_data = ConversationData(**conv_data_raw)

                        # Filter by user_id
                        if (
                            not hasattr(conv_data, "user_id")
                            or conv_data.user_id != user_id
                        ):
                            continue

                        conversations.append(
                            Conversation(
                                id=conv_data.conversation_id,
                                title=f"Conversation {conv_data.conversation_id[:8]}",
                                messages=conv_data.messages,
                                created_at=conv_data.updated_at,
                                updated_at=conv_data.updated_at,
                            )
                        )
                except Exception as e:
                    logger.warning(f"Failed to load conversation from {key}: {e}")
                    continue

            if cursor == 0:
                break

        return conversations[offset : offset + limit]

    except Exception as e:
        logger.error(f"Failed to list conversations: {e}")
        return []


async def create_conversation(
    redis_client,
    conversation_id: str,
    title: Optional[str] = None,
    user_id: Optional[str] = None,
) -> "Conversation":
    """Create a new conversation."""
    conversation = await load_or_create_conversation(
        redis_client, conversation_id, user_id
    )

    return Conversation(
        id=conversation.conversation_id,
        title=title or f"Conversation {conversation_id[:8]}",
        messages=conversation.messages,
        created_at=conversation.updated_at,
        updated_at=conversation.updated_at,
    )


async def update_conversation_title(
    redis_client, conversation_id: str, title: str, user_id: Optional[str] = None
) -> Optional["Conversation"]:
    """Update conversation title (stored in metadata).

    Args:
        redis_client: Redis client
        conversation_id: Conversation ID to update
        title: New conversation title
        user_id: Optional user ID for ownership validation
    """
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if not conversation_data:
            return None

        # ✅ SECURITY: If user_id provided, validate ownership before update
        if (
            user_id
            and conversation_data.get("user_id")
            and conversation_data.get("user_id") != user_id
        ):
            logger.warning(
                f"User {user_id} attempted to update conversation {conversation_id}"
            )
            return None

        if "metadata" not in conversation_data:
            conversation_data["metadata"] = {}
        conversation_data["metadata"]["title"] = title
        conversation_data["updated_at"] = datetime.now().isoformat()

        await redis_client.json().set(conversation_key, "$", conversation_data)

        conv_data = ConversationData(**conversation_data)
        return Conversation(
            id=conv_data.conversation_id,
            title=title,
            messages=conv_data.messages,
            created_at=conv_data.updated_at,
            updated_at=conv_data.updated_at,
        )

    except Exception as e:
        logger.error(f"Failed to update conversation title: {e}")
        return None


async def delete_conversation(
    redis_client, conversation_id: str, user_id: Optional[str] = None
) -> bool:
    """Delete a conversation.

    Args:
        redis_client: Redis client
        conversation_id: Conversation ID to delete
        user_id: Optional user ID for ownership validation
    """
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)

        # Check ownership before delete
        conversation_data = await redis_client.json().get(conversation_key)
        if not conversation_data:
            return False

        # ✅ SECURITY: If user_id provided, validate ownership before delete
        if (
            user_id
            and conversation_data.get("user_id")
            and conversation_data.get("user_id") != user_id
        ):
            logger.warning(
                f"User {user_id} attempted to delete conversation {conversation_id}"
            )
            return False

        result = await redis_client.delete(conversation_key)
        return result > 0

    except Exception as e:
        logger.error(f"Failed to delete conversation {conversation_id}: {e}")
        return False


class Conversation:
    """Conversation model for API responses."""

    def __init__(
        self,
        id: str,
        title: str,
        messages: list,
        created_at: datetime,
        updated_at: datetime,
    ):
        self.id = id
        self.title = title
        self.messages = messages
        self.created_at = created_at
        self.updated_at = updated_at
