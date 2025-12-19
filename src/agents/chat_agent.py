import json
import logging
from typing import Any, Dict, List

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt
from src.agents.base_agent import BaseAgent
from src.services.chat_data_service import reconstruct_full_data
from src.typing.llm_response.chat_agent import ChatAgentResponse
from src.typing.redis import RedisChannels
from src.typing.request import ChatRequest
from src.typing.schema import ChatAgentSchema, LLMMarkdownField
from src.utils.converstation import load_or_create_conversation
from src.utils.shared_data_utils import (
    get_shared_data,
    save_shared_data,
    truncate_results,
)

logger = logging.getLogger(__name__)

AGENT_TYPE = "chat_agent"


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(AGENT_TYPE)]

    async def get_conversation_history(
        self, conversation_id: str
    ) -> List[Dict[str, Any]]:
        if conversation_id:
            conversation = await load_or_create_conversation(
                self.redis, conversation_id
            )
            return conversation.get_recent_messages(limit=10)
        return []

    def compose_llm_messages(
        self, query: str, context: Dict[str, Any], history: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        messages = [
            {"role": "system", "content": build_system_prompt()},
            *history,
            {
                "role": "user",
                "content": build_chat_agent_prompt(query=query, context=context),
            },
        ]
        return messages

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    chat_request = ChatRequest.model_validate_json(message["data"])
                    await self.handle_command_message(chat_request)
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def handle_command_message(self, chat_request: ChatRequest):
        try:
            query_id = chat_request.query_id
            chat_result: ChatAgentSchema = await self.process(chat_request)

            # mark the shared data as completed
            shared_data = await get_shared_data(self.redis, query_id)
            shared_data.status = "completed"
            await save_shared_data(self.redis, query_id, shared_data)

            # Publish the chat result
            await self.publish_channel(
                RedisChannels.get_query_completion_channel(query_id),
                chat_result,
                ChatAgentSchema,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"Error executing chat request: {e}")

    async def process(self, request: ChatRequest) -> ChatAgentSchema:
        try:
            shared_data = await get_shared_data(self.redis, request.query_id)
            if not shared_data:
                return self.create_fallback_response(
                    request.query_id, request.conversation_id
                )

            history = await self.get_conversation_history(request.conversation_id)

            raw_context = request.context or {}

            llm_context = {
                **raw_context,
                "results": truncate_results(raw_context.get("results", {})),
            }

            messages = self.compose_llm_messages(request.query, llm_context, history)

            chat_agent_layout: ChatAgentSchema = await self.call_llm(
                query_id=request.query_id,
                messages=messages,
                response_schema=ChatAgentSchema,
            )

            if not chat_agent_layout:
                return self.create_fallback_response()

            full_data = reconstruct_full_data(shared_data)

            result = ChatAgentResponse(
                layout=chat_agent_layout.layout, full_data=full_data
            )

            return result

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self.create_error_response(str(e))

    def create_fallback_response(self) -> ChatAgentSchema:
        return ChatAgentSchema(
            layout=[
                LLMMarkdownField(
                    content="## Response\n\nI received your query but couldn't process it. Please try again."
                )
            ]
        )

    def create_error_response(self, error: str) -> ChatAgentSchema:
        return (
            ChatAgentSchema(
                layout=[
                    LLMMarkdownField(
                        content=f"## Processing Error\n\nSorry, I encountered an error: {error}"
                    )
                ]
            ),
        )

    async def start(self):
        await self.listen_channels()
