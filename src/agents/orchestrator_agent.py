import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts import build_orchestrator_prompt

from src.agents.chat_agent import AGENT_TYPE as CHAT_AGENT_TYPE
from src.agents.summary_agent import AGENT_TYPE as SUMMARY_AGENT_TYPE
from src.typing.llm_response import OrchestratorResponse
from src.typing.redis import (
    CommandMessage,
    CompletionResponse,
    ConversationData,
    LLMUsage,
    QueryTask,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.request import ChatRequest, Request
from src.typing.schema import OrchestratorSchema
from src.utils import get_shared_data, save_shared_data

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "OrchestratorAgent"


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_type=CHAT_AGENT_TYPE)
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def process(self, request: Request) -> OrchestratorResponse:
        try:
            if not request.query:
                return OrchestratorResponse(
                    error="Query cannot be empty",
                )

            history = []
            if request.conversation_id:
                conversation = await self._load_or_create_conversation(
                    request.conversation_id
                )
                history = conversation.get_recent_messages(limit=10)

            messages = [
                {"role": "system", "content": self.prompt},
                *history,
                {"role": "user", "content": request.query},
            ]

            response_content: OrchestratorResponse = await self._call_llm(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                messages=messages,
                response_schema=OrchestratorSchema,
                response_model=OrchestratorResponse,
            )

            if request.conversation_id and response_content:
                await self._save_conversation_message(
                    request.conversation_id, "user", request.query
                )

            return response_content

        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return OrchestratorResponse(
                error=f"Processing error: {str(e)[:100]}",
            )

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    if message["channel"] == RedisChannels.TASK_UPDATES:
                        task_update_message = TaskUpdate.model_validate_json(
                            message["data"]
                        )
                        await self._handle_task_update(task_update_message)
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_task_update(self, task_update_message: TaskUpdate):
        try:
            shared_data: SharedData = await self._update_shared_data_tasks(
                task_update_message
            )
            if not shared_data:
                return

            if task_update_message.agent_type == CHAT_AGENT_TYPE:
                await self._publish_final_completion(task_update_message)
            elif shared_data.is_complete:
                await self._trigger_chat_agent(shared_data)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
        except Exception as e:
            logger.error(f"Task update processing error: {e}")

    async def _update_shared_data_tasks(
        self, task_update_message: TaskUpdate
    ) -> Optional[SharedData]:
        try:
            shared_data: SharedData = await get_shared_data(
                self.redis, task_update_message.query_id
            )
            if not shared_data:
                logger.warning(
                    f"No shared data for query {task_update_message.query_id}"
                )
                return None

            if (
                task_update_message.status == TaskStatus.DONE
                and task_update_message.result
            ):
                shared_data.complete_task(
                    task_update_message.task_id, task_update_message.result
                )

            # Update LLM usage metrics
            if task_update_message.llm_usage:
                usage_key = (
                    f"{task_update_message.agent_type}_{task_update_message.query_id}"
                )

                shared_data.llm_usage[usage_key] = LLMUsage(
                    **task_update_message.llm_usage
                )

            # Save updated shared data atomically
            await save_shared_data(
                self.redis, task_update_message.query_id, shared_data
            )

            return shared_data

        except Exception as e:
            logger.error(
                f"Task execution update failed for {task_update_message.query_id}: {e}"
            )
            return None

    async def _trigger_chat_agent(self, shared_data: SharedData):
        logger.info(
            f"All tasks done for query {shared_data.query_id}, triggering ChatAgent"
        )

        try:
            all_results = {}

            for agent_type in shared_data.agents_needed:
                agent_results = shared_data.get_agent_results(agent_type)
                if agent_results:
                    all_results[agent_type] = agent_results

            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_needed,
                "results": self._filter_results_for_context(all_results),
            }

            chat_message = ChatRequest(
                query_id=shared_data.query_id,
                conversation_id=shared_data.conversation_id,
                context=filtered_context,
            )

            chat_channel = RedisChannels.get_command_channel(CHAT_AGENT_TYPE)
            await self.redis.publish(chat_channel, chat_message.model_dump_json())
            logger.info(
                f"Successfully triggered ChatAgent for query {shared_data.query_id}"
            )

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {shared_data.query_id}: {e}")

            error_response = CompletionResponse.response_error(
                query_id=shared_data.query_id,
                error="ChatAgent trigger failed - using fallback response",
                original_query=shared_data.original_query,
                conversation_id=shared_data.conversation_id,
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                shared_data.query_id
            )
            await self.redis.publish(
                completion_channel, error_response.model_dump_json()
            )

    async def _trigger_summary_agent(self, query_id: str, shared_data: SharedData):
        try:
            conversation_id = shared_data.conversation_id
            if not conversation_id:
                return

            summary_message = CommandMessage(
                query_id=query_id,
                conversation_id=conversation_id,
                agent_type=SUMMARY_AGENT_TYPE,
                command="summarize",
            )

            summary_channel = RedisChannels.get_command_channel(SUMMARY_AGENT_TYPE)
            await self.redis.publish(summary_channel, json.dumps(summary_message))

        except Exception as e:
            logger.error(f"Failed to trigger SummaryAgent for {query_id}: {e}")

    async def _publish_final_completion(self, task_update_message: TaskUpdate):
        try:
            shared_data = await get_shared_data(
                self.redis, task_update_message.query_id
            )
            if not shared_data:
                logger.warning(
                    f"No shared data for completion of {task_update_message.query_id}"
                )
                return

            final_response_text = None

            if task_update_message.result:
                if isinstance(task_update_message.result, dict):
                    final_response_text = task_update_message.result.get(
                        "final_response"
                    )

            # Validate required response content
            if not final_response_text:
                logger.warning(
                    f"Empty response from ChatAgent for {task_update_message.query_id}"
                )
                final_response_text = "Processing completed successfully."

            # Create structured completion response
            completion_response = CompletionResponse.response_success(
                query_id=task_update_message.query_id,
                conversation_id=shared_data.conversation_id,
                original_query=shared_data.original_query,
                response=final_response_text,
            )

            completion_key = RedisChannels.get_query_completion_channel(
                task_update_message.query_id
            )

            await self.redis.publish(
                completion_key, completion_response.model_dump_json()
            )

            await self._store_completion_metrics(
                task_update_message, shared_data, completion_response
            )

            await self._trigger_summary_agent(task_update_message.query_id, shared_data)

        except Exception as e:
            logger.error(
                f"Failed to publish final completion for {task_update_message.query_id}: {e}"
            )

            # Structured fallback response
            await self._publish_fallback_completion(task_update_message, str(e))

    async def _store_completion_metrics(
        self,
        task_update_message: TaskUpdate,
        shared_data: "SharedData",
        completion_response: "CompletionResponse",
    ):
        try:
            # Collect agent results for internal monitoring
            agent_results = {}
            for agent_type in shared_data.agents_needed:
                results = shared_data.get_agent_results(agent_type)
                if results:
                    agent_results[agent_type] = results

            # Internal metrics payload
            internal_metrics = {
                "query_id": task_update_message.query_id,
                "completion_response_id": f"comp_{task_update_message.query_id}",
                "agent_results": agent_results,
                "execution_summary": shared_data.execution_summary,
                "llm_usage": {},
                "processing_metadata": {
                    "agents_involved": shared_data.agents_needed,
                    "total_tasks": len(shared_data.tasks),
                    "completion_timestamp": datetime.now().isoformat(),
                    "response_length": len(completion_response.response or ""),
                },
            }

            # Serialize LLM usage metrics
            if task_update_message.llm_usage:
                internal_metrics["llm_usage"][task_update_message.agent_type] = (
                    task_update_message.llm_usage
                )

            for usage_key, llm_usage in shared_data.llm_usage.items():
                if hasattr(llm_usage, "model_dump"):
                    internal_metrics["llm_usage"][usage_key] = llm_usage.model_dump()

            # Store with TTL for monitoring/billing
            metrics_key = f"metrics:{task_update_message.query_id}"
            await self.redis.json().set(metrics_key, "$", internal_metrics)
            await self.redis.expire(metrics_key, 86400)  # 24 hours

            logger.debug(
                f"Stored completion metrics for {task_update_message.query_id}"
            )

        except Exception as e:
            logger.error(f"Failed to store completion metrics: {e}")

    async def _publish_fallback_completion(
        self, task_update_message: TaskUpdate, error_details: str
    ):
        try:
            shared_data = await get_shared_data(
                self.redis, task_update_message.query_id
            )
            original_query = (
                shared_data.original_query if shared_data else "Unknown query"
            )

            # Create structured error response
            error_response = CompletionResponse.response_error(
                query_id=task_update_message.query_id,
                error="Processing completed but response generation failed",
                original_query=original_query,
                conversation_id=shared_data.conversation_id if shared_data else None,
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                task_update_message.query_id
            )

            completion_json = error_response.model_dump_json(exclude_none=True)
            await self.redis.publish(completion_channel, completion_json)

            logger.info(
                f"Published fallback completion for {task_update_message.query_id}"
            )

        except Exception as fallback_error:
            logger.error(f"Fallback completion failed: {fallback_error}")

    def _filter_results_for_context(
        self,
        results: Dict[str, Any],
        max_items: int = 10,
        max_depth: int = 5,
        _current_depth: int = 0,
    ) -> Dict[str, Any]:
        """
        Recursively filter nested agent results for ChatAgent context.
        - Dict: recurse into values (up to max_depth)
        - List: take up to max_items elements, recurse if elements are dict/list
        - Other types: include as-is
        Security: Prevents memory exhaustion and stack overflow via size/depth limits.
        """
        if not results or not isinstance(results, dict):
            return {}

        if _current_depth > max_depth:
            logger.warning("Max recursion depth reached in context filtering")
            return {"_truncated": True}

        filtered = {}
        for key, value in results.items():
            if isinstance(value, dict):
                filtered[key] = self._filter_results_for_context(
                    value,
                    max_items=max_items,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
            elif isinstance(value, list):
                filtered_list = []
                for item in value[:max_items]:
                    if isinstance(item, (dict, list)):
                        filtered_list.append(
                            self._filter_results_for_context(
                                item if isinstance(item, dict) else {"list": item},
                                max_items=max_items,
                                max_depth=max_depth,
                                _current_depth=_current_depth + 1,
                            )
                            if isinstance(item, dict)
                            else [
                                self._filter_results_for_context(
                                    {"list": subitem},
                                    max_items=max_items,
                                    max_depth=max_depth,
                                    _current_depth=_current_depth + 1,
                                )
                                if isinstance(subitem, dict)
                                else subitem
                                for subitem in item
                            ]
                        )
                    else:
                        filtered_list.append(item)
                filtered[key] = filtered_list
                if len(value) > max_items:
                    filtered[key].append(
                        {"_truncated": True, "total_items": len(value)}
                    )
            else:
                filtered[key] = value
        return filtered

    async def _load_or_create_conversation(
        self, conversation_id: str
    ) -> ConversationData:
        conversation_key = RedisKeys.get_conversation_key(conversation_id)

        try:
            logger.info(
                f"OrchestratorAgent: Loading conversation with key: {conversation_key}"
            )
            conversation_data = await self.redis.json().get(conversation_key)

            if conversation_data:
                logger.info(
                    f"OrchestratorAgent: Found existing conversation {conversation_id} with {len(conversation_data.get('messages', []))} messages"
                )
                return ConversationData(**conversation_data)
            else:
                logger.info(
                    f"OrchestratorAgent: Creating new conversation {conversation_id}"
                )
                new_conversation = ConversationData(
                    conversation_id=conversation_id,
                    messages=[],
                    updated_at=datetime.now(),
                    max_messages=50,  # Keep last 50 messages
                )
                await self.redis.json().set(
                    conversation_key,
                    "$",
                    json.loads(json.dumps(new_conversation.model_dump())),
                )
                logger.info(
                    f"OrchestratorAgent: Created new conversation: {conversation_id}"
                )
                return new_conversation

        except Exception as e:
            logger.warning(
                f"OrchestratorAgent: Error loading conversation, creating new: {e}"
            )
            return ConversationData(
                conversation_id=conversation_id, messages=[], updated_at=datetime.now()
            )

    async def _save_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        try:
            logger.info(
                f"OrchestratorAgent: Loading/creating conversation {conversation_id} for saving message"
            )
            conversation = await self._load_or_create_conversation(conversation_id)

            conversation.add_message(role=role, content=content, metadata=metadata)

            conversation_key = RedisKeys.get_conversation_key(conversation_id)
            await self.redis.json().set(
                conversation_key,
                "$",
                json.loads(json.dumps(conversation.model_dump())),
            )

            logger.info(
                f"OrchestratorAgent: Saved {role} message to conversation {conversation_id} "
                f"(total: {len(conversation.messages)} messages)"
            )

        except Exception as e:
            logger.error(f"OrchestratorAgent: Failed to save conversation message: {e}")

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in await self.get_pub_channels():
            raise ValueError(f"OrchestratorAgent cannot publish to {channel}")

        try:
            if not isinstance(message, QueryTask):
                message = QueryTask(**message)
            await self.redis.publish(channel=channel, message=message.model_dump_json())
            logger.info(f"{self.agent_type} published on {channel}: {message}")
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def start(self):
        logger.info("OrchestratorAgent: Starting workflow orchestration")
        await self.listen_channels()
