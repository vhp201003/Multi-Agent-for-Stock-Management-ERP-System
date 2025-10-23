import json
import logging
from datetime import datetime
from typing import Optional

from src.typing.redis import ConversationData, RedisKeys

logger = logging.getLogger(__name__)


async def load_or_create_conversation(redis, conversation_id: str) -> ConversationData:
    conversation_key = RedisKeys.get_conversation_key(conversation_id)

    try:
        logger.info(f"Loading conversation with key: {conversation_key}")
        conversation_data = await redis.json().get(conversation_key)

        if conversation_data:
            logger.info(
                f"Found existing conversation {conversation_id} with {len(conversation_data.get('messages', []))} messages"
            )
            return ConversationData(**conversation_data)
        else:
            logger.info(f"Creating new conversation {conversation_id}")
            new_conversation = ConversationData(
                conversation_id=conversation_id,
                messages=[],
                updated_at=datetime.now(),
                max_messages=50,  # Keep last 50 messages
            )
            await redis.json().set(
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
    redis,
    conversation_id: str,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
):
    try:
        logger.info(
            f"Loading/creating conversation {conversation_id} for saving message"
        )
        conversation = await load_or_create_conversation(redis, conversation_id)

        conversation.add_message(role=role, content=content, metadata=metadata)

        conversation_key = RedisKeys.get_conversation_key(conversation_id)
        await redis.json().set(
            conversation_key,
            "$",
            json.loads(conversation.model_dump_json()),
        )

        logger.info(
            f"Saved {role} message to conversation {conversation_id} (total: {len(conversation.messages)} messages)"
        )

    except Exception as e:
        logger.error(f"Failed to save conversation message: {e}")
