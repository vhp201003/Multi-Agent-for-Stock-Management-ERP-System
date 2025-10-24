import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt

from src.agents.base_agent import BaseAgent
from src.typing.llm_response import ChatResponse
from src.typing.redis import CompletionResponse, RedisChannels, TaskStatus, TaskUpdate
from src.typing.request import ChatRequest
from src.typing.schema import (
    ChatAgentSchema,
    LLMGraphField,
    LLMMarkdownField,
    LLMSectionBreakField,
    LLMTableField,
)
from src.utils.converstation import save_conversation_message
from src.utils.shared_data_utils import get_shared_data

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
        full_data = None
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            shared_data = await get_shared_data(self.redis, request.query_id)
            if not shared_data:
                return self._create_fallback_response(
                    request.query_id, request.conversation_id, None
                )

            all_results = {}
            for agent_type in shared_data.agents_needed:
                agent_results = shared_data.get_agent_results(agent_type)
                if agent_results:
                    all_results[agent_type] = agent_results
            full_data = all_results

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
                response.result.full_data = full_data
                # Fill actual data into graph fields
                self._fill_data_from_full_data(response.result, full_data)
                return response
            else:
                return self._create_fallback_response(
                    request.query_id, request.conversation_id, full_data
                )

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self._create_error_response(
                str(e), request.query_id, request.conversation_id, full_data
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

            # Publish task update for orchestrator to trigger summary
            task_update = TaskUpdate(
                query_id=response.query_id,
                agent_type=self.agent_type,
                task_id=f"{self.agent_type}_{response.query_id}",
                status=TaskStatus.DONE,
                result=response.result.model_dump()
                if response.result
                else {"error": "No response"},
                llm_usage=response.llm_usage,
            )
            await self.publish_channel(
                RedisChannels.TASK_UPDATES, task_update, TaskUpdate
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
        self._fill_data_from_full_data(schema, full_context)
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
        self._fill_data_from_full_data(schema, full_context)
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=schema,
        )

    def _fill_data_from_full_data(
        self, schema: ChatAgentSchema, full_data: Optional[Dict[str, Any]]
    ):
        """Fill actual data from full_data into graph and table fields in layout."""
        if not full_data or not schema.layout:
            return

        for field in schema.layout:
            if isinstance(field, LLMGraphField):
                # Try to fill graph data based on available data
                graph_data = self._extract_graph_data(full_data, field.title)
                if graph_data:
                    field.data = graph_data
            elif isinstance(field, LLMTableField):
                # Try to fill table data based on available data
                table_data = self._extract_table_data(full_data, field.title)
                if table_data:
                    field.data = table_data

    def _extract_graph_data(
        self, full_data: Dict[str, Any], title: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract data for graph from full_data based on available tools."""
        try:
            # Check for inventory stock data
            if "inventory" in full_data:
                return self._extract_stock_graph_data(full_data)
            # Add more data types as needed
        except Exception as e:
            logger.warning(f"Failed to extract graph data: {e}")
        return None

    def _extract_table_data(
        self, full_data: Dict[str, Any], title: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract data for table from full_data based on available tools."""
        try:
            # Check for inventory stock data
            if "inventory" in full_data:
                return self._extract_stock_table_data(full_data)
            # Add more data types as needed
        except Exception as e:
            logger.warning(f"Failed to extract table data: {e}")
        return None

    def _extract_stock_graph_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Extract stock level data for graph from full_data."""
        try:
            if "inventory" in full_data:
                history_data = []
                for task_key, task_data in full_data["inventory"].items():
                    if "tool_results" in task_data:
                        for tool_result in task_data["tool_results"]:
                            if tool_result.get("tool_name") == "retrieve_stock_history":
                                # This is stock history data
                                result_data = tool_result.get("tool_result", {})
                                if isinstance(result_data, list) and result_data:
                                    # List of stock history entries
                                    for entry in result_data:
                                        if isinstance(entry, dict):
                                            date = entry.get("date") or entry.get(
                                                "timestamp"
                                            )
                                            quantity = (
                                                entry.get("quantity")
                                                or entry.get("balance")
                                                or entry.get("stock_level")
                                            )
                                            if date and quantity is not None:
                                                history_data.append(
                                                    {
                                                        "date": str(date),
                                                        "quantity": int(quantity),
                                                    }
                                                )
                                elif isinstance(result_data, dict):
                                    # Single entry or different format
                                    # Try to extract if it has multiple entries
                                    pass

                if history_data:
                    # Sort by date and create chart data
                    history_data.sort(key=lambda x: x["date"])
                    labels = [entry["date"] for entry in history_data]
                    data = [entry["quantity"] for entry in history_data]
                    return {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": "Stock Level",
                                "data": data,
                                "borderColor": "blue",
                                "fill": False,
                            }
                        ],
                    }
                else:
                    # Fallback to current stock level
                    for task_key, task_data in full_data["inventory"].items():
                        if "tool_results" in task_data:
                            for tool_result in task_data["tool_results"]:
                                if tool_result.get("tool_name") == "check_stock":
                                    stock_info = tool_result.get("tool_result", {})
                                    stock_level = stock_info.get("stock_level")
                                    if stock_level is not None:
                                        return {
                                            "labels": ["Current Stock"],
                                            "datasets": [
                                                {
                                                    "label": "Stock Level",
                                                    "data": [int(stock_level)],
                                                }
                                            ],
                                        }
        except Exception as e:
            logger.warning(f"Failed to extract stock graph data: {e}")
        return None

    def _extract_stock_table_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Extract stock level data for table from full_data."""
        try:
            if "inventory" in full_data:
                # Try stock history first for table
                for task_key, task_data in full_data["inventory"].items():
                    if "tool_results" in task_data:
                        for tool_result in task_data["tool_results"]:
                            if tool_result.get("tool_name") == "retrieve_stock_history":
                                result_data = tool_result.get("tool_result", [])
                                if isinstance(result_data, list) and result_data:
                                    headers = ["Date", "Quantity"]
                                    rows = [
                                        [
                                            entry.get("date", ""),
                                            entry.get("quantity", 0),
                                        ]
                                        for entry in result_data
                                    ]
                                    return {"headers": headers, "rows": rows}

                # Fallback to current stock level
                for task_key, task_data in full_data["inventory"].items():
                    if "tool_results" in task_data:
                        for tool_result in task_data["tool_results"]:
                            if tool_result.get("tool_name") == "check_stock":
                                stock_info = tool_result.get("tool_result", {})
                                stock_level = stock_info.get("stock_level")
                                if stock_level is not None:
                                    headers = ["Item", "Stock Level"]
                                    rows = [["Current Stock", stock_level]]
                                    return {"headers": headers, "rows": rows}
        except Exception as e:
            logger.warning(f"Failed to extract stock table data: {e}")
        return None

    async def start(self):
        await self.listen_channels()
