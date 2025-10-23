import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt

from src.agents.base_agent import BaseAgent
from src.typing.llm_response import ChatResponse
from src.typing.redis import CompletionResponse, RedisChannels
from src.typing.request import ChatRequest
from src.typing.schema import (
    ChatAgentSchema,
    LLMMarkdownField,
    LLMSectionBreakField,
)
from src.utils.converstation import save_conversation_message

logger = logging.getLogger(__name__)

AGENT_TYPE = "chat_agent"


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_COMPLETION]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(AGENT_TYPE)]

    async def process(self, request: ChatRequest) -> ChatResponse:
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            messages = [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_chat_agent_prompt(
                        query=request.query, context=request.context
                    ),
                },
            ]

            response = await self._call_llm(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                messages=messages,
                response_schema=ChatAgentSchema,
                response_model=ChatResponse,
            )

            if isinstance(response, ChatResponse) and response.result:
                # Add full_data to the schema
                response.result.full_data = request.full_context
                return response
            else:
                return self._create_fallback_response(
                    request.query_id, request.conversation_id, request.full_context
                )

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self._create_error_response(
                str(e), request.query_id, request.conversation_id, request.full_context
            )

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

    async def handle_command_message(self, chat_request=ChatRequest):
        try:
            response: ChatResponse = await self.process(chat_request)

            await self.publish_completion(response)

            # Store chat history
            await save_conversation_message(
                self.redis,
                chat_request.conversation_id,
                "assistant",
                response.result.model_dump_json() if response.result else "No response",
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"Error executing chat request: {e}")

    async def publish_completion(self, response: ChatResponse):
        try:
            completion_channel = RedisChannels.get_query_completion_channel(
                response.query_id
            )

            # Publish final completion response
            completion_response = CompletionResponse.response_success(
                query_id=response.query_id,
                conversation_id=response.conversation_id,
                response=response.result.model_dump()
                if response.result
                else {"error": "No response"},
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                response.query_id
            )
            await self.publish_channel(
                completion_channel,
                completion_response,
                CompletionResponse,
            )

        except Exception as e:
            logger.error(f"Failed to publish completion for {response.query_id}: {e}")

    def _create_fallback_response(
        self,
        query_id: str,
        conversation_id: Optional[str],
        full_context: Optional[Dict[str, Any]],
    ) -> ChatResponse:
        schema = ChatAgentSchema(
            layout=[
                LLMSectionBreakField(
                    title="Response",
                ),
                LLMMarkdownField(
                    content=f"I received your query: **{query_id}**\n\nLet me help you with that. Please provide more specific details for a better response.",
                ),
            ]
        )
        schema.full_data = full_context
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=schema,
        )

    def _create_error_response(
        self,
        error: str,
        query_id: str,
        conversation_id: Optional[str],
        full_context: Optional[Dict[str, Any]],
    ) -> ChatResponse:
        schema = ChatAgentSchema(
            layout=[
                LLMSectionBreakField(
                    title="Error",
                ),
                LLMMarkdownField(
                    content=f"**Processing Error**\n\nSorry, I encountered an error: {error}",
                ),
            ]
        )
        schema.full_data = full_context
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=schema,
        )

    async def start(self):
        await self.listen_channels()
