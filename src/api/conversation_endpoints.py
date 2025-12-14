"""
Conversation management API endpoints.
Provides CRUD operations for conversations stored in Redis.
"""

import logging
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.services.quick_actions import generate_quick_actions
from src.utils.converstation import (
    Conversation,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    load_or_create_conversation,
    update_conversation_title,
)

logger = logging.getLogger(__name__)


# Request/Response Models
class ConversationCreateRequest(BaseModel):
    conversation_id: str = Field(..., description="Unique conversation ID")
    title: Optional[str] = Field(None, description="Conversation title")


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., description="New conversation title")


class MessageResponse(BaseModel):
    role: str
    content: str
    timestamp: str
    metadata: Optional[dict] = None


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    messages: List[MessageResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total: int


class QuickActionsResponse(BaseModel):
    conversation_id: str
    suggestions: List[str] = Field(
        ..., description="List of 3 contextual quick action suggestions"
    )


# Endpoint Handlers
async def create_conversation_handler(
    redis, request: ConversationCreateRequest, user_id: str
) -> ConversationResponse:
    """Create a new conversation."""
    try:
        conversation = await create_conversation(
            redis, request.conversation_id, request.title, user_id
        )
        return conversation_to_response(conversation)
    except Exception as e:
        logger.error(f"Failed to create conversation: {e}")
        raise HTTPException(status_code=500, detail=f"Creation failed: {str(e)}")


async def get_conversation_handler(
    redis,
    conversation_id: str,
    user_id: Optional[str] = None,
    include_messages: bool = False,
) -> ConversationResponse:
    """Get a single conversation by ID.

    Args:
        redis: Redis client
        conversation_id: Conversation ID to retrieve
        user_id: Optional user ID for ownership validation
        include_messages: Whether to include messages in response
    """
    try:
        conversation = await get_conversation(redis, conversation_id, user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return conversation_to_response(conversation, include_messages)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")


async def list_conversations_handler(
    redis, user_id: str, limit: int = 50, offset: int = 0
) -> ConversationListResponse:
    """List all conversations with pagination."""
    try:
        conversations = await list_conversations(
            redis, user_id, limit=limit, offset=offset
        )

        # Sort by updated_at descending (most recent first)
        sorted_conversations = sorted(
            conversations, key=lambda c: c.updated_at, reverse=True
        )

        responses = [
            conversation_to_response(conv, include_messages=False)
            for conv in sorted_conversations
        ]

        return ConversationListResponse(conversations=responses, total=len(responses))
    except Exception as e:
        logger.error(f"Failed to list conversations: {e}")
        raise HTTPException(status_code=500, detail=f"List failed: {str(e)}")


async def update_conversation_handler(
    redis,
    conversation_id: str,
    request: ConversationUpdateRequest,
    user_id: Optional[str] = None,
) -> ConversationResponse:
    """Update conversation title.

    Args:
        redis: Redis client
        conversation_id: Conversation ID to update
        request: Update request with new title
        user_id: Optional user ID for ownership validation
    """
    try:
        conversation = await update_conversation_title(
            redis, conversation_id, request.title, user_id
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return conversation_to_response(conversation)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


async def delete_conversation_handler(
    redis, conversation_id: str, user_id: Optional[str] = None
) -> dict:
    """Delete a conversation.

    Args:
        redis: Redis client
        conversation_id: Conversation ID to delete
        user_id: Optional user ID for ownership validation
    """
    try:
        success = await delete_conversation(redis, conversation_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return {"status": "success", "conversation_id": conversation_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")


async def get_quick_actions_handler(
    redis, llm_client, conversation_id: str, user_id: Optional[str] = None
) -> QuickActionsResponse:
    """Get or generate quick action suggestions for a conversation.

    Args:
        redis: Redis client
        llm_client: LLM client for generating suggestions
        conversation_id: Conversation ID to get quick actions for
        user_id: Optional user ID for ownership validation

    Returns:
        QuickActionsResponse with suggestions

    Raises:
        HTTPException: If conversation not found or generation fails
    """
    try:
        # Verify conversation exists and user has access
        conversation_data = await load_or_create_conversation(
            redis, conversation_id, user_id
        )

        # Check if we have cached quick actions
        if conversation_data.quick_actions:
            logger.info(
                f"Returning cached quick actions for conversation {conversation_id}"
            )
            return QuickActionsResponse(
                conversation_id=conversation_id,
                suggestions=conversation_data.quick_actions,
            )

        # Generate new quick actions
        suggestions = await generate_quick_actions(conversation_id)

        if not suggestions:
            raise HTTPException(
                status_code=500,
                detail="Failed to generate quick actions. Not enough conversation context.",
            )

        return QuickActionsResponse(
            conversation_id=conversation_id, suggestions=suggestions
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get quick actions for {conversation_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Quick actions retrieval failed: {str(e)}"
        )


# Helper Functions
def conversation_to_response(
    conversation: Conversation, include_messages: bool = False
) -> ConversationResponse:
    """Convert Conversation object to API response."""
    messages = []
    if include_messages:
        messages = [
            MessageResponse(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp.isoformat()
                if hasattr(msg.timestamp, "isoformat")
                else str(msg.timestamp),
                metadata=msg.metadata if hasattr(msg, "metadata") else None,
            )
            for msg in conversation.messages
        ]

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        message_count=len(conversation.messages),
        messages=messages,
    )
