import json
import logging
from datetime import datetime
from typing import List

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt

from src.agents.base_agent import BaseAgent
from src.typing.llm_response import ChatResponse
from src.typing.redis import RedisChannels, TaskStatus, TaskUpdate
from src.typing.request import ChatRequest
from src.typing.schema import (
    ChatAgentSchema,
    LLMMarkdownField,
    LLMSectionBreakField,
)

logger = logging.getLogger(__name__)

AGENT_TYPE = "chat_agent"


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(AGENT_TYPE)]

    async def process(self, request: ChatRequest) -> ChatResponse:
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            context_str = json.dumps(request.context) if request.context else "None"

            messages = [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_chat_agent_prompt(
                        query=request.query, context=context_str
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

            if isinstance(response, ChatResponse):
                return response
            else:
                return self._create_fallback_response(request.query)

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self._create_error_response(str(e))

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    chat_request = ChatRequest.model_dump_json(message["data"])
                    await self._handle_command_consolidated(chat_request)
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_command_consolidated(self, chat_request=ChatRequest):
        try:
            response: ChatResponse = await self.process(chat_request)

            await self.publish_completion(response)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"Error executing chat request: {e}")

    async def publish_completion(self, response: ChatResponse):
        try:
            task_update = TaskUpdate(
                agent_type=AGENT_TYPE,
                query_id=response.query_id,
                status=TaskStatus.DONE,
                result={
                    "final_response": response.result.model_dump(),
                    "layout_response": response.model_dump(),
                    "field_count": len(response.layout),
                    "response_type": "structured_layout",
                },
                llm_usage=response.llm_usage,
                llm_reasoning=response.llm_reasoning,
            )

            await self.redis.publish(
                RedisChannels.TASK_UPDATES, task_update.model_dump_json()
            )

        except Exception as e:
            logger.error(f"Failed to publish completion for {response.query_id}: {e}")

    def _create_fallback_response(self, query: str) -> ChatResponse:
        schema = ChatAgentSchema(
            layout=[
                LLMSectionBreakField(
                    title="Response",
                ),
                LLMMarkdownField(
                    content=f"I received your query: **{query}**\n\nLet me help you with that. Please provide more specific details for a better response.",
                ),
            ]
        )
        return ChatResponse(
            result=schema,
            metadata={"generated_at": datetime.now().isoformat(), "fallback": True},
        )

    def _create_error_response(self, error: str) -> ChatResponse:
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
        return ChatResponse(
            result=schema,
            metadata={"generated_at": datetime.now().isoformat(), "error": True},
        )

    async def start(self):
        await self.listen_channels()
