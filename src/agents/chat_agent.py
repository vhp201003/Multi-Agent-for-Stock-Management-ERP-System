import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts.chat_agent import build_chat_agent_prompt, build_system_prompt

from src.agents.base_agent import BaseAgent
from src.typing.llm_response import ChatResponse
from src.typing.redis import RedisChannels, SharedData, TaskStatus, TaskUpdate
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

            filtered_context = request.context or {}

            full_data = self._reconstruct_full_data_from_references(
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

            response = await self._call_llm(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                messages=messages,
                response_schema=ChatAgentSchema,
                response_model=ChatResponse,
            )

            if isinstance(response, ChatResponse) and response.result:
                response.result.full_data = full_data
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

            await self.publish_completion(response, chat_request.query)

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
        """
        Fill actual data from full_data into graph and table fields in layout.

        full_data structure (from result_references):
        {
            "inventory": {
                "check_stock": {"tool_name": "check_stock", "data": {...}, "agent_type": "inventory"},
                "get_history": {"tool_name": "get_history", "data": {...}, "agent_type": "inventory"}
            }
        }
        """
        if not full_data or not schema.layout:
            return

        for field in schema.layout:
            if isinstance(field, LLMGraphField):
                graph_data = self._extract_graph_data(full_data, field.title)
                if graph_data:
                    field.data = graph_data
            elif isinstance(field, LLMTableField):
                table_data = self._extract_table_data(full_data, field.title)
                if table_data:
                    field.data = table_data

    def _extract_graph_data(
        self, full_data: Dict[str, Any], title: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract data for graph from full_data using generic detection."""
        try:
            return self._extract_generic_graph_data(full_data)
        except Exception as e:
            logger.warning(f"Failed to extract graph data: {e}")
        return None

    def _extract_table_data(
        self, full_data: Dict[str, Any], title: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Extract data for table from full_data using generic detection."""
        try:
            return self._extract_generic_table_data(full_data)
        except Exception as e:
            logger.warning(f"Failed to extract table data: {e}")
        return None

    def _reconstruct_full_data_from_references(
        self, shared_data: "SharedData", filtered_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        full_data = {}

        try:
            if not filtered_context or "results" not in filtered_context:
                return full_data

            results = filtered_context.get("results", {})

            for agent_type, agent_results in results.items():
                if not isinstance(agent_results, dict):
                    continue

                agent_full_data = {}

                for tool_name, tool_info in agent_results.items():
                    if isinstance(tool_info, dict) and "result_id" in tool_info:
                        result_id = tool_info["result_id"]
                        full_result = shared_data.get_result_by_id(result_id)
                        if full_result:
                            agent_full_data[tool_name] = full_result
                    else:
                        agent_full_data[tool_name] = tool_info

                if agent_full_data:
                    full_data[agent_type] = agent_full_data

            logger.debug(f"Reconstructed full_data for {len(full_data)} agents")
            return full_data

        except Exception as e:
            logger.warning(f"Failed to reconstruct full_data from references: {e}")
            return full_data

    def _extract_generic_graph_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            for _, agent_tools in full_data.items():
                if not isinstance(agent_tools, dict):
                    continue

                for tool_name, tool_result in agent_tools.items():
                    if not isinstance(tool_result, dict):
                        continue

                    raw_data = tool_result.get("data", tool_result)

                    if isinstance(raw_data, list) and len(raw_data) > 0:
                        first_entry = raw_data[0]
                        if isinstance(first_entry, dict):
                            date_keys = [
                                k
                                for k in first_entry.keys()
                                if "date" in k.lower() or "time" in k.lower()
                            ]
                            value_keys = [
                                k
                                for k in first_entry.keys()
                                if "quantity" in k.lower()
                                or "amount" in k.lower()
                                or "value" in k.lower()
                                or "level" in k.lower()
                                or "stock" in k.lower()
                            ]

                            if date_keys and value_keys:
                                labels = []
                                values = []
                                for entry in raw_data:
                                    date_val = entry.get(date_keys[0])
                                    val = entry.get(value_keys[0])
                                    if date_val is not None and val is not None:
                                        labels.append(str(date_val))
                                        values.append(
                                            int(val)
                                            if isinstance(val, (int, float))
                                            else 0
                                        )

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

    def _extract_generic_table_data(
        self, full_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generic table data extraction: find first list of objects in tools."""
        try:
            for agent_type, agent_tools in full_data.items():
                if not isinstance(agent_tools, dict):
                    continue

                for tool_name, tool_result in agent_tools.items():
                    if not isinstance(tool_result, dict):
                        continue

                    raw_data = tool_result.get("data", tool_result)

                    if isinstance(raw_data, list) and len(raw_data) > 0:
                        first_entry = raw_data[0]
                        if isinstance(first_entry, dict):
                            columns = list(first_entry.keys())
                            rows = []
                            for entry in raw_data:
                                row = {}
                                for col in columns:
                                    row[col] = entry.get(col, "")
                                rows.append(row)

                            if rows:
                                return {
                                    "columns": columns,
                                    "rows": rows,
                                }

                    elif isinstance(raw_data, dict):
                        columns = list(raw_data.keys())
                        rows = [{col: raw_data.get(col, "") for col in columns}]
                        return {
                            "columns": columns,
                            "rows": rows,
                        }

            return None
        except Exception as e:
            logger.debug(f"Generic table extraction failed: {e}")
            return None

    async def start(self):
        await self.listen_channels()
