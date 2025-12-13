import json
import logging
from typing import List, Optional

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt
from src.agents.base_agent import BaseAgent
from src.services.chat_data_service import reconstruct_full_data
from src.typing.llm_response import ChatResponse
from src.typing.redis import RedisChannels, TaskStatus, TaskUpdate
from src.typing.request import ChatRequest
from src.typing.schema import ChatAgentSchema, LLMMarkdownField
from src.utils.converstation import save_conversation_message
from src.utils.shared_data_utils import get_shared_data, truncate_results

logger = logging.getLogger(__name__)

AGENT_TYPE = "chat_agent"


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(AGENT_TYPE)]

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
            response: ChatResponse = await self.process(chat_request)
            await self.publish_completion(response, chat_request.query)

            if response.result:
                result_dict = response.result.model_dump()

                content_dict = {
                    k: v for k, v in result_dict.items() if k != "full_data"
                }

                await save_conversation_message(
                    self.redis,
                    chat_request.conversation_id,
                    "assistant",
                    json.dumps(content_dict, ensure_ascii=False),
                    metadata={
                        "full_data": result_dict.get("full_data"),
                    },
                )
            else:
                await save_conversation_message(
                    self.redis,
                    chat_request.conversation_id,
                    "assistant",
                    "No response",
                )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"Error executing chat request: {e}")

    async def process(self, request: ChatRequest) -> ChatResponse:
        try:
            shared_data = await get_shared_data(self.redis, request.query_id)
            if not shared_data:
                return self.create_fallback_response(
                    request.query_id, request.conversation_id
                )

            raw_context = request.context or {}
            llm_context = {
                **raw_context,
                "results": truncate_results(raw_context.get("results", {})),
            }

            messages = [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_chat_agent_prompt(
                        query=request.query, context=llm_context
                    ),
                },
            ]

            result, llm_usage, llm_reasoning = await self.call_llm(
                query_id=request.query_id,
                messages=messages,
                response_schema=ChatAgentSchema,
            )

            if not result:
                return self.create_fallback_response(
                    request.query_id, request.conversation_id
                )

            result.full_data = reconstruct_full_data(shared_data)

            return ChatResponse(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                result=result,
                llm_usage=llm_usage,
                llm_reasoning=llm_reasoning,
            )

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self.create_error_response(
                str(e), request.query_id, request.conversation_id
            )

    async def publish_completion(self, response: ChatResponse, sub_query: str):
        try:
            task_update = TaskUpdate(
                query_id=response.query_id,
                task_id=f"{self.agent_type}_{response.query_id}",
                agent_type=self.agent_type,
                sub_query=sub_query,
                status=TaskStatus.DONE,
                result={
                    "final_response": response.result.model_dump()
                    if response.result
                    else {"error": "No response"}
                },
                llm_usage=response.llm_usage or {},
            )
            await self.publish_channel(
                RedisChannels.TASK_UPDATES, task_update, TaskUpdate
            )
        except Exception as e:
            logger.error(f"Failed to publish completion for {response.query_id}: {e}")

    def create_fallback_response(
        self, query_id: str, conversation_id: Optional[str]
    ) -> ChatResponse:
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=ChatAgentSchema(
                layout=[
                    LLMMarkdownField(
                        content="## Response\n\nI received your query but couldn't process it. Please try again."
                    )
                ]
            ),
        )

    def create_error_response(
        self, error: str, query_id: str, conversation_id: Optional[str]
    ) -> ChatResponse:
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=ChatAgentSchema(
                layout=[
                    LLMMarkdownField(
                        content=f"## Processing Error\n\nSorry, I encountered an error: {error}"
                    )
                ]
            ),
            llm_usage={},
        )

    async def start(self):
        await self.listen_channels()
