import json
import logging
from datetime import datetime
from typing import Optional

from src.typing.redis import ConversationData, RedisKeys

logger = logging.getLogger(__name__)


async def load_or_create_conversation(
    redis_client, conversation_id: str
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
                max_messages=50,  # Keep last 50 messages
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


async def get_conversation(
    redis_client, conversation_id: str
) -> Optional["Conversation"]:
    """Get a conversation by ID with proper model."""
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if not conversation_data:
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
    redis_client, limit: int = 50, offset: int = 0
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
    redis_client, conversation_id: str, title: Optional[str] = None
) -> "Conversation":
    """Create a new conversation."""
    conversation = await load_or_create_conversation(redis_client, conversation_id)

    return Conversation(
        id=conversation.conversation_id,
        title=title or f"Conversation {conversation_id[:8]}",
        messages=conversation.messages,
        created_at=conversation.updated_at,
        updated_at=conversation.updated_at,
    )


async def update_conversation_title(
    redis_client, conversation_id: str, title: str
) -> Optional["Conversation"]:
    """Update conversation title (stored in metadata)."""
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        conversation_data = await redis_client.json().get(conversation_key)

        if not conversation_data:
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


async def delete_conversation(redis_client, conversation_id: str) -> bool:
    """Delete a conversation."""
    try:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)
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
