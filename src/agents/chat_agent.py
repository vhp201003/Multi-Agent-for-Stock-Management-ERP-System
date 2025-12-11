import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt
from src.agents.base_agent import BaseAgent
from src.services.chart_data_mapper import ChartDataMapper
from src.typing.llm_response import ChatResponse
from src.typing.redis import RedisChannels, SharedData, TaskStatus, TaskUpdate
from src.typing.request import ChatRequest
from src.typing.schema import (
    ChatAgentSchema,
    LLMGraphField,
    LLMMarkdownField,
    LLMTableField,
)
from src.utils.converstation import save_conversation_message
from src.utils.shared_data_utils import get_shared_data

logger = logging.getLogger(__name__)

AGENT_TYPE = "chat_agent"


class ChatAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(AGENT_TYPE)]

    async def process(self, request: ChatRequest) -> ChatResponse:
        full_data = None
        try:
            logger.info(f"Processing chat request: {request.query[:100]}...")

            shared_data = await get_shared_data(self.redis, request.query_id)
            if not shared_data:
                return self.create_fallback_response(
                    request.query_id, request.conversation_id, None
                )

            filtered_context = request.context or {}

            full_data = self.reconstruct_full_data_from_references(
                shared_data, filtered_context
            )

            messages = [
                {"role": "system", "content": build_system_prompt()},
                {
                    "role": "user",
                    "content": build_chat_agent_prompt(
                        query=request.query, context=filtered_context
                    ),
                },
            ]

            result, llm_usage, llm_reasoning = await self.call_llm(
                query_id=request.query_id,
                messages=messages,
                response_schema=ChatAgentSchema,
            )

            response = ChatResponse(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                result=result,
                llm_usage=llm_usage,
                llm_reasoning=llm_reasoning,
            )

            if isinstance(response, ChatResponse) and response.result:
                response.result.full_data = full_data
                self.fill_data_from_full_data(response.result, full_data)
                return response
            else:
                return self.create_fallback_response(
                    request.query_id, request.conversation_id, full_data
                )

        except Exception as e:
            logger.error(f"Chat processing failed: {e}")
            return self.create_error_response(
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

            await self.publish_completion(response, chat_request.query)

            if response.result:
                result_dict = response.result.model_dump()

                metadata = {
                    "layout": result_dict.get("layout"),
                    "full_data": result_dict.get("full_data"),
                }

                await save_conversation_message(
                    self.redis,
                    chat_request.conversation_id,
                    "assistant",
                    response.result.model_dump_json(),
                    metadata=metadata,
                )

                logger.debug(
                    f"Saved conversation message for {chat_request.conversation_id}"
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
                llm_usage=response.llm_usage or {},  # Ensure dict, never None
            )
            await self.publish_channel(
                RedisChannels.TASK_UPDATES, task_update, TaskUpdate
            )
        except Exception as e:
            logger.error(f"Failed to publish completion for {response.query_id}: {e}")

    def create_fallback_response(
        self,
        query_id: str,
        conversation_id: Optional[str],
        full_context: Optional[Dict[str, Any]],
    ) -> ChatResponse:
        schema = ChatAgentSchema(
            layout=[
                LLMMarkdownField(
                    content=f"## Response\n\nI received your query: **{query_id}**\n\nLet me help you with that. Please provide more specific details for a better response.",
                ),
            ]
        )
        schema.full_data = full_context
        self.fill_data_from_full_data(schema, full_context)
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=schema,
        )

    def create_error_response(
        self,
        error: str,
        query_id: str,
        conversation_id: Optional[str],
        full_context: Optional[Dict[str, Any]],
    ) -> ChatResponse:
        schema = ChatAgentSchema(
            layout=[
                LLMMarkdownField(
                    content=f"## Processing Error\n\nSorry, I encountered an error: {error}",
                ),
            ]
        )
        schema.full_data = full_context
        self.fill_data_from_full_data(schema, full_context)
        return ChatResponse(
            query_id=query_id,
            conversation_id=conversation_id,
            result=schema,
            llm_usage={},  # Empty dict instead of None to satisfy Pydantic validation
        )

    def fill_data_from_full_data(
        self, schema: ChatAgentSchema, full_data: Optional[Dict[str, Any]]
    ):
        if not full_data or not schema.layout:
            return

        for field in schema.layout:
            if isinstance(field, LLMGraphField) and field.data_source:
                chart_data = ChartDataMapper.extract_chart_data(
                    full_data=full_data,
                    data_source=field.data_source,
                    graph_type=field.graph_type,
                )

                if chart_data:
                    field.data = chart_data

                    # Detect format type for safe logging
                    if "chartData" in chart_data:
                        count = len(chart_data["chartData"])
                        format_type = "recharts"
                    else:
                        count = len(chart_data.get("labels", []))
                        format_type = "legacy"

                    logger.info(
                        f"Populated chart '{field.title}' ({format_type}): "
                        f"{count} points from "
                        f"{field.data_source.agent_type}.{field.data_source.tool_name}"
                    )
                else:
                    logger.warning(
                        f"Failed to populate chart '{field.title}'. "
                        f"Source: {field.data_source.agent_type}.{field.data_source.tool_name}"
                    )

            elif isinstance(field, LLMTableField):
                table_data = self.extract_table_data(full_data, field.title)
                if table_data:
                    field.data = table_data

    def extract_table_data(
        self, full_data: Dict[str, Any], title: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract data for table from full_data using generic detection."""
        try:
            return self.extract_generic_table_data(full_data)
        except Exception as e:
            logger.warning(f"Failed to extract table data: {e}")
        return None

    def reconstruct_full_data_from_references(
        self, shared_data: "SharedData", filtered_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        from src.utils.agent_helpers import traverse_full_data

        full_data = {}

        try:
            if not filtered_context or "results" not in filtered_context:
                return full_data

            results = filtered_context.get("results", {})

            # Group by agent_type as we traverse
            for agent_type, task_id, task_result in traverse_full_data(results):
                if not isinstance(task_result, dict):
                    continue

                # Initialize agent data if needed
                if agent_type not in full_data:
                    full_data[agent_type] = {}

                # Resolve result_id reference if present
                if "result_id" in task_result:
                    full_result = shared_data.get_result_by_id(task_result["result_id"])
                    if full_result:
                        task_result = full_result

                # Extract tool results to top level
                if "tool_results" in task_result:
                    for tool_item in task_result["tool_results"]:
                        if isinstance(tool_item, dict) and "tool_name" in tool_item:
                            tool_name = tool_item["tool_name"]
                            tool_result = tool_item.get("tool_result", {})
                            full_data[agent_type][tool_name] = tool_result

                # Store task result
                full_data[agent_type][task_id] = task_result

            logger.debug(f"Reconstructed full_data for {len(full_data)} agents")
            return full_data

        except Exception as e:
            logger.warning(f"Failed to reconstruct full_data from references: {e}")
            return full_data

    def extract_generic_graph_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        from src.utils.agent_helpers import traverse_full_data

        try:
            for agent_type, tool_name, tool_result in traverse_full_data(full_data):
                if not isinstance(tool_result, dict):
                    continue

                raw_data = tool_result.get("data", tool_result)

                if not (isinstance(raw_data, list) and len(raw_data) > 0):
                    continue

                first_entry = raw_data[0]
                if not isinstance(first_entry, dict):
                    continue

                # Find date/time and value keys
                date_keys = [
                    k
                    for k in first_entry.keys()
                    if "date" in k.lower() or "time" in k.lower()
                ]
                value_keys = [
                    k
                    for k in first_entry.keys()
                    if any(
                        term in k.lower()
                        for term in ["quantity", "amount", "value", "level", "stock"]
                    )
                ]

                if not (date_keys and value_keys):
                    continue

                # Extract labels and values
                labels, values = [], []
                for entry in raw_data:
                    date_val = entry.get(date_keys[0])
                    val = entry.get(value_keys[0])
                    if date_val is not None and val is not None:
                        labels.append(str(date_val))
                        values.append(int(val) if isinstance(val, (int, float)) else 0)

                if labels and values:
                    return {
                        "labels": labels,
                        "datasets": [
                            {
                                "label": tool_name,
                                "data": values,
                                "borderColor": "blue",
                                "fill": False,
                            }
                        ],
                    }

            return None
        except Exception as e:
            logger.debug(f"Generic graph extraction failed: {e}")
            return None

    def extract_generic_table_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generic table data extraction: find first list of objects in tools."""
        from src.utils.agent_helpers import traverse_full_data

        try:
            for agent_type, tool_name, tool_result in traverse_full_data(full_data):
                if not isinstance(tool_result, dict):
                    continue

                raw_data = tool_result.get("data", tool_result)

                # Handle list of dicts
                if isinstance(raw_data, list) and len(raw_data) > 0:
                    first_entry = raw_data[0]
                    if isinstance(first_entry, dict):
                        columns = list(first_entry.keys())
                        rows = [
                            {col: entry.get(col, "") for col in columns}
                            for entry in raw_data
                        ]
                        if rows:
                            return {"columns": columns, "rows": rows}

                # Handle single dict
                elif isinstance(raw_data, dict):
                    columns = list(raw_data.keys())
                    rows = [{col: raw_data.get(col, "") for col in columns}]
                    return {"columns": columns, "rows": rows}

            return None
        except Exception as e:
            logger.debug(f"Generic table extraction failed: {e}")
            return None

    async def start(self):
        await self.listen_channels()
