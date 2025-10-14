import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts.chat_agent import CHAT_AGENT_PROMPTS

from src.agents.base_agent import BaseAgent
from src.typing.chat_layout import (
    ChatRequest,
    ChatResponse,
    FieldType,
    MarkdownLayoutField,
    SectionBreakLayoutField,
)
from src.typing.redis import RedisChannels, RedisKeys, SharedData
from src.typing.schema import ChatAgentSchema

logger = logging.getLogger(__name__)


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type="chat_agent", **kwargs)
        self.layout_prompts = CHAT_AGENT_PROMPTS

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel("chat_agent")]

    async def process(self, request: ChatRequest) -> ChatResponse:
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            context_str = json.dumps(request.context) if request.context else "None"
            layout_prompt = self.layout_prompts["user_template"].format(
                query=request.query, context=context_str
            )

            messages = [
                {"role": "system", "content": self.layout_prompts["system"]},
                {"role": "user", "content": self.layout_prompts["layout_guidelines"]},
                {"role": "user", "content": layout_prompt},
            ]

            response = await self._call_llm(
                messages=messages,
                response_schema=ChatAgentSchema,
                response_model=ChatResponse,
            )

            if isinstance(response, ChatResponse):
                logger.info(f"Generated layout with {len(response.layout)} fields")
                return response
            else:
                logger.error(f"LLM returned invalid response: {response}")
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
                    await self._handle_command_consolidated(message["data"])
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_command_consolidated(self, raw_data: str):
        try:
            data = json.loads(raw_data)
            command = data.get("command")

            if command != "execute":
                return

            query_id = data.get("query_id")
            sub_query = data.get("sub_query")

            if not query_id or not sub_query:
                logger.error("Missing query_id or sub_query in command")
                return

            logger.info(f"DEBUG: sub_query type: {type(sub_query)}, value: {sub_query}")

            if isinstance(sub_query, str):
                chat_request = ChatRequest(query=sub_query)
            elif isinstance(sub_query, dict):
                context = sub_query.get("context")
                query_text = sub_query.get("query", "")
                logger.info(f"DEBUG: Creating ChatRequest with query='{query_text}', context type: {type(context)}")
                chat_request = ChatRequest(query=query_text, context=context)
            else:
                logger.error(f"Invalid sub_query type: {type(sub_query)}, value: {sub_query}")
                return

            response = await self.process(chat_request)
            await self._publish_completion_consolidated(query_id, sub_query, response)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in command message: {e}")
        except Exception as e:
            logger.error(f"Error executing chat request: {e}")

    async def _publish_completion_consolidated(self, query_id: str, sub_query: Any, response: ChatResponse):
        try:
            sub_query_str = (
                sub_query.get("query", "") if isinstance(sub_query, dict) else str(sub_query)
            )

            task_id = await self._resolve_task_id_inline(query_id, sub_query_str)

            llm_usage_data = {}
            if hasattr(response, "llm_usage") and response.llm_usage:
                if isinstance(response.llm_usage, dict):
                    llm_usage_data = response.llm_usage
                elif hasattr(response.llm_usage, "model_dump"):
                    llm_usage_data = response.llm_usage.model_dump()
                else:
                    llm_usage_data = {
                        attr: getattr(response.llm_usage, attr, None)
                        for attr in ["completion_tokens", "prompt_tokens", "total_tokens",
                                   "completion_time", "prompt_time", "queue_time", "total_time"]
                    }

            completion_message = {
                "query_id": query_id,
                "sub_query": sub_query_str,
                "task_id": task_id,
                "status": "done",
                "results": {
                    "final_response": response.model_dump(),
                    "layout_response": response.model_dump(),
                    "field_count": len(response.layout),
                    "response_type": "structured_layout",
                },
                "context": {
                    "agent_type": "chat_agent",
                    "final_agent": True,
                    "response_ready": True,
                },
                "llm_usage": llm_usage_data,
                "timestamp": datetime.now().isoformat(),
                "agent_type": "chat_agent",
            }

            await self.publish_channel(RedisChannels.TASK_UPDATES, completion_message)
            logger.info(f"Published FINAL completion for query {query_id}")

        except Exception as e:
            logger.error(f"Failed to publish completion for {query_id}: {e}")

    async def _resolve_task_id_inline(self, query_id: str, sub_query: str) -> Optional[str]:
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data_raw = await self.redis.json().get(shared_key)

            if not shared_data_raw:
                logger.warning(f"No shared data for query {query_id}")
                return "chat_1"  # Fallback

            shared_data = SharedData(**shared_data_raw)

            if "chat_agent" in shared_data.task_graph.nodes:
                for task in shared_data.task_graph.nodes["chat_agent"]:
                    if (task.sub_query == sub_query or 
                        "Generate final response" in task.sub_query or
                        "final response" in sub_query.lower()):
                        return task.task_id

            logger.info(f"ChatAgent task not found in graph, using fallback ID for {query_id}")
            return "chat_1"

        except Exception as e:
            logger.error(f"ChatAgent task ID resolution failed for {query_id}: {e}")
            return "chat_1"

    def _create_fallback_response(self, query: str) -> ChatResponse:
        return ChatResponse(
            layout=[
                SectionBreakLayoutField(title="Response"),
                MarkdownLayoutField(
                    content=f"I received your query: **{query}**\\n\\nLet me help you with that. Please provide more specific details for a better response.",
                    field_type=FieldType.MARKDOWN,
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "fallback": True},
        )

    def _create_error_response(self, error: str) -> ChatResponse:
        return ChatResponse(
            layout=[
                SectionBreakLayoutField(title="Error"),
                MarkdownLayoutField(
                    content=f"**Processing Error**\\n\\nSorry, I encountered an error: {error}",
                    field_type=FieldType.MARKDOWN,
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "error": True},
        )

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        try:
            await self.redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            raise

    async def start(self):
        await self.listen_channels()