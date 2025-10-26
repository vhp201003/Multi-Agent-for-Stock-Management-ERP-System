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
    LLMUsage,
    QueryTask,
    RedisChannels,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.request import ChatRequest, Request
from src.typing.schema import OrchestratorSchema
from src.utils import get_shared_data, save_shared_data
from src.utils.converstation import (
    load_or_create_conversation,
    save_conversation_message,
)

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

    async def process_query(self, request: Request) -> Dict[str, Any]:
        try:
            await self.process(request)
            completion_data: CompletionResponse = await self._wait_for_completion(
                request.query_id
            )
            return completion_data.model_dump()

        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return {"status": "error", "error": f"Processing error: {str(e)}"}

    async def process(self, request: Request) -> None:
        try:
            validation_error = self._validate_request(request)
            if validation_error:
                raise ValueError(validation_error)

            request = self._ensure_conversation_id(request)
            history = await self._get_conversation_history(request)
            messages = self._compose_llm_messages(request, history)
            orchestration_result = await self._run_llm_orchestration(request, messages)
            logger.info(f"Orchestration result: {orchestration_result}")
            if request.conversation_id and orchestration_result:
                await save_conversation_message(
                    self.redis, request.conversation_id, "user", request.query
                )

            error = self._validate_orchestration_result(orchestration_result)
            if error:
                raise ValueError(error)

            await self._initialize_shared_state(request, orchestration_result)
            sub_query_dict = self._build_sub_query_dict(orchestration_result)
            if not sub_query_dict:
                raise ValueError("No valid sub-queries found for orchestration")

            await self._publish_orchestration_task(request, sub_query_dict)

        except Exception as e:
            logger.error(f"LLM orchestration failed: {e}")
            raise

    def _validate_request(self, request: Request) -> Optional[str]:
        if not request.query or not request.query.strip():
            return "Query cannot be empty"
        if not request.query_id or not request.query_id.strip():
            return "Query ID cannot be empty"
        return None

    def _ensure_conversation_id(self, request: Request):
        if not hasattr(request, "conversation_id") or not request.conversation_id:
            request.conversation_id = request.query_id
        return request

    async def _get_conversation_history(self, request: Request) -> List[Any]:
        if request.conversation_id:
            conversation = await load_or_create_conversation(
                self.redis, request.conversation_id
            )
            return conversation.get_recent_messages(limit=10)
        return []

    def _compose_llm_messages(
        self, request: Request, history: List[Any]
    ) -> List[Dict[str, Any]]:
        return [
            {"role": "system", "content": self.prompt},
            *history,
            {"role": "user", "content": request.query},
        ]

    async def _run_llm_orchestration(
        self, request: Request, messages: List[Dict[str, Any]]
    ) -> OrchestratorResponse:
        return await self._call_llm(
            query_id=request.query_id,
            conversation_id=request.conversation_id,
            messages=messages,
            response_schema=OrchestratorSchema,
            response_model=OrchestratorResponse,
        )

    def _validate_orchestration_result(
        self, orchestration_result: OrchestratorResponse
    ) -> Optional[str]:
        if orchestration_result.error:
            return orchestration_result.error
        if (
            not orchestration_result.result
            or not orchestration_result.result.agents_needed
        ):
            return "No agents identified for query processing"
        return None

    async def _initialize_shared_state(
        self, request: Request, orchestration_result: OrchestratorResponse
    ) -> SharedData:
        shared_data = SharedData(
            original_query=request.query,
            query_id=request.query_id,
            agents_needed=orchestration_result.result.agents_needed,
            status="processing",
            conversation_id=request.conversation_id,
        )
        for (
            agent_type,
            task_list,
        ) in orchestration_result.result.task_dependency.items():
            for task in task_list:
                shared_data.add_task(task)
        await save_shared_data(self.redis, request.query_id, shared_data)

    def _build_sub_query_dict(
        self, orchestration_result: OrchestratorResponse
    ) -> Dict[str, List[str]]:
        sub_query_dict = {}
        for (
            agent_type,
            task_list,
        ) in orchestration_result.result.task_dependency.items():
            if task_list:
                sub_query_list = [task.sub_query for task in task_list]
                if sub_query_list:
                    sub_query_dict[agent_type] = sub_query_list
        return sub_query_dict

    async def _publish_orchestration_task(
        self, request: Request, sub_query_dict: Dict[str, List[str]]
    ):
        message = QueryTask(
            query_id=request.query_id,
            agents_needed=list(sub_query_dict.keys()),
            sub_query=sub_query_dict,
        )
        await self.publish_channel(RedisChannels.QUERY_CHANNEL, message, QueryTask)

    async def _wait_for_completion(self, query_id: str) -> Dict[str, Any]:
        completion_channel = RedisChannels.get_query_completion_channel(query_id)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(completion_channel)
        try:
            start_time = datetime.now().timestamp()
            max_wait_time = 300.0  # 5 minutes
            async for message in pubsub.listen():
                if message["type"] == "message":
                    completion_data: CompletionResponse = (
                        CompletionResponse.model_validate_json(message["data"])
                    )
                    if completion_data.query_id == query_id:
                        await pubsub.unsubscribe(completion_channel)
                        await pubsub.aclose()
                        return completion_data
                if (datetime.now().timestamp() - start_time) > max_wait_time:
                    await pubsub.unsubscribe(completion_channel)
                    await pubsub.aclose()
                    return {"status": "error", "error": "Query completion timeout"}
        except Exception as e:
            await pubsub.unsubscribe(completion_channel)
            await pubsub.aclose()
            return {
                "status": "error",
                "error": f"Error waiting for completion: {str(e)[:100]}",
            }

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if (
                    message["channel"] == RedisChannels.TASK_UPDATES
                    and message["type"] == "message"
                ):
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
                query=shared_data.original_query,
                context=filtered_context,
            )

            chat_channel = RedisChannels.get_command_channel(CHAT_AGENT_TYPE)
            await self.publish_channel(chat_channel, chat_message, ChatRequest)
            logger.info(
                f"Successfully triggered ChatAgent for query {shared_data.query_id}"
            )

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {shared_data.query_id}: {e}")

            error_response = CompletionResponse.response_error(
                query_id=shared_data.query_id,
                error="ChatAgent trigger failed - using fallback response",
                conversation_id=shared_data.conversation_id,
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                shared_data.query_id
            )
            await self.publish_channel(
                completion_channel, error_response, CompletionResponse
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
            await self.publish_channel(summary_channel, summary_message, CommandMessage)

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
                response={"final_response": final_response_text},
            )

            completion_key = RedisChannels.get_query_completion_channel(
                task_update_message.query_id
            )

            await self.publish_channel(
                completion_key, completion_response, CompletionResponse
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
                    "response_length": len(str(completion_response.response))
                    if completion_response.response
                    else 0,
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

            # Create structured error response
            error_response = CompletionResponse.response_error(
                query_id=task_update_message.query_id,
                error="Processing completed but response generation failed",
                conversation_id=shared_data.conversation_id if shared_data else None,
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                task_update_message.query_id
            )

            await self.publish_channel(
                completion_channel, error_response, CompletionResponse
            )

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

    async def start(self):
        logger.info("OrchestratorAgent: Starting workflow orchestration")
        await self.listen_channels()
