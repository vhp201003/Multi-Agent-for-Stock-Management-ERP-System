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
    """
    ChatAgent generates structured layout responses for professional UI rendering.

    Capabilities:
    - Text and rich content formatting
    - Data visualization (charts, graphs)
    - Tabular data presentation
    - Metrics and KPI displays
    - Alert and notification systems
    - Layout control (columns, sections, breaks)
    """

    def __init__(self, **kwargs):
        super().__init__(agent_type="chat_agent", **kwargs)
        self.layout_prompts = CHAT_AGENT_PROMPTS

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel("chat_agent")]

    async def process(self, request: ChatRequest) -> ChatResponse:
        """
        Process chat request and generate structured layout response.

        Args:
            request: ChatRequest with query and preferences

        Returns:
            ChatResponse with structured layout fields
        """
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            messages = [
                {"role": "system", "content": self.layout_prompts["system"]},
                {"role": "user", "content": self.layout_prompts["layout_guidelines"]},
                {"role": "user", "content": self._build_layout_prompt(request)},
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
            logger.error(f"Chat processing failed: {e}", exc_info=True)
            return self._create_error_response(str(e))

    def _build_layout_prompt(self, request: ChatRequest) -> str:
        logger.info(
            f"DEBUG: Building prompt with request.context type: {type(request.context)}"
        )
        logger.info(f"DEBUG: request.context value: {request.context}")

        context_str = json.dumps(request.context) if request.context else "None"

        prompt = self.layout_prompts["user_template"].format(
            query=request.query, context=context_str
        )
        return prompt

    def _create_fallback_response(self, query: str) -> ChatResponse:
        return ChatResponse(
            layout=[
                SectionBreakLayoutField(title="Response"),
                MarkdownLayoutField(
                    content=f"I received your query: **{query}**\n\nLet me help you with that. Please provide more specific details for a better response.",
                    field_type=FieldType.MARKDOWN,
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "fallback": True},
        )

    def _extract_llm_usage(self, response: ChatResponse) -> dict:
        llm_usage_data = {}
        if hasattr(response, "llm_usage") and response.llm_usage:
            if isinstance(response.llm_usage, dict):
                llm_usage_data = response.llm_usage
            elif hasattr(response.llm_usage, "model_dump"):
                llm_usage_data = response.llm_usage.model_dump()
            else:
                llm_usage_data = {
                    "completion_tokens": getattr(
                        response.llm_usage, "completion_tokens", None
                    ),
                    "prompt_tokens": getattr(response.llm_usage, "prompt_tokens", None),
                    "total_tokens": getattr(response.llm_usage, "total_tokens", None),
                    "completion_time": getattr(
                        response.llm_usage, "completion_time", None
                    ),
                    "prompt_time": getattr(response.llm_usage, "prompt_time", None),
                    "queue_time": getattr(response.llm_usage, "queue_time", None),
                    "total_time": getattr(response.llm_usage, "total_time", None),
                }
        return llm_usage_data

    def _create_error_response(self, error: str) -> ChatResponse:
        return ChatResponse(
            layout=[
                SectionBreakLayoutField(title="Error"),
                MarkdownLayoutField(
                    content=f"**Processing Error**\n\nSorry, I encountered an error: {error}",
                    field_type=FieldType.MARKDOWN,
                ),
            ],
            metadata={"generated_at": datetime.now().isoformat(), "error": True},
        )

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        logger.info(f"ChatAgent listening on channels: {channels}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self._handle_command_message(data)
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_command_message(self, data: Dict[str, Any]):
        command = data.get("command")

        if command == "execute":
            query_id = data.get("query_id")
            sub_query = data.get("sub_query")

            if not query_id or not sub_query:
                logger.error("Missing query_id or sub_query in command")
                return

            try:
                logger.info(
                    f"DEBUG: sub_query type: {type(sub_query)}, value: {sub_query}"
                )

                if isinstance(sub_query, str):
                    chat_request = ChatRequest(query=sub_query)
                elif isinstance(sub_query, dict):
                    context = sub_query.get("context")
                    query_text = sub_query.get("query", "")

                    logger.info(
                        f"DEBUG: Creating ChatRequest with query='{query_text}', context type: {type(context)}"
                    )

                    chat_request = ChatRequest(
                        query=query_text,
                        context=context,
                    )
                else:
                    logger.error(
                        f"Invalid sub_query type: {type(sub_query)}, value: {sub_query}"
                    )
                    return

                response = await self.process(chat_request)

                await self._publish_completion(query_id, sub_query, response)

            except Exception as e:
                logger.error(f"Error executing chat request: {e}")
                await self._publish_error(query_id, sub_query, str(e))

    async def _publish_completion(
        self, query_id: str, sub_query: Any, response: ChatResponse
    ):
        sub_query_str = (
            sub_query.get("query", "")
            if isinstance(sub_query, dict)
            else str(sub_query)
        )

        task_id = await self._resolve_task_id(query_id, sub_query_str)

        completion_message = {
            "query_id": query_id,
            "sub_query": sub_query_str,
            "task_id": task_id,  # Include for task_graph tracking
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
            "llm_usage": self._extract_llm_usage(response),
            "timestamp": datetime.now().isoformat(),
            "agent_type": "chat_agent",
        }

        channel = RedisChannels.TASK_UPDATES
        await self.publish_channel(channel, completion_message)
        logger.info(f"Published FINAL completion for query {query_id}")

    async def _resolve_task_id(self, query_id: str, sub_query: str) -> Optional[str]:
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data_raw = await self.redis.json().get(shared_key)

            if not shared_data_raw:
                logger.warning(f"No shared data for query {query_id}")
                return None

            shared_data = SharedData(**shared_data_raw)

            if "chat_agent" in shared_data.task_graph.nodes:
                for task in shared_data.task_graph.nodes["chat_agent"]:
                    if (
                        task.sub_query == sub_query
                        or "Generate final response" in task.sub_query
                        or "final response" in sub_query.lower()
                    ):
                        return task.task_id

            logger.info(
                f"ChatAgent task not found in graph, using fallback ID for {query_id}"
            )
            return "chat_1"

        except Exception as e:
            logger.error(f"ChatAgent task ID resolution failed for {query_id}: {e}")
            return "chat_1"  # Fail-safe fallback

    async def _publish_error(self, query_id: str, sub_query: Any, error: str):
        sub_query_str = (
            sub_query.get("query", "")
            if isinstance(sub_query, dict)
            else str(sub_query)
        )

        error_message = {
            "query_id": query_id,
            "sub_query": sub_query_str,  # FIXED: Ensure string type
            "status": "error",
            "results": {},  # REQUIRED field
            "context": {"agent_type": "chat_agent", "error": error},
            "llm_usage": {},  # REQUIRED field
            "timestamp": datetime.now().isoformat(),
            "agent_type": "chat_agent",  # Include agent type for easier identification
        }

        channel = RedisChannels.TASK_UPDATES
        await self.publish_channel(channel, error_message)

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        try:
            await self.redis.publish(channel, json.dumps(message))
            logger.debug(f"Published to {channel}: {message}")
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            raise

    async def start(self):
        """Start the ChatAgent."""
        logger.info("Starting ChatAgent...")
        await self.listen_channels()
