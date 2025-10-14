import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts import build_orchestrator_prompt

from src.typing.redis import (
    ConversationData,
    Message,
    QueryTask,
    RedisChannels,
    RedisKeys,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.request import Request
from src.typing.response import OrchestratorResponse
from src.typing.schema import OrchestratorSchema
from src.utils import update_shared_data

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "OrchestratorAgent"


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_type=AGENT_TYPE)
        self.prompt = build_orchestrator_prompt(
            OrchestratorSchema
        )

    def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]  # Listen to unified task updates channel

    async def handle_task_update_message(
        self, channel: str, task_update_message: TaskUpdate
    ):
        if channel != RedisChannels.TASK_UPDATES:
            logger.warning(f"OrchestratorAgent: Invalid channel: {channel}")
            return

        agent_type = self._extract_agent_type_from_update(task_update_message)
        query_id = task_update_message.query_id

        if not query_id:
            logger.error("Missing query_id in task update")
            return

        try:
            logger.info(
                f"DEBUG: About to update shared data for query_id {query_id}, agent_type {agent_type}"
            )

            shared_data = await self._update_shared_data_atomic(
                query_id, agent_type, task_update_message
            )

            if not shared_data:
                logger.warning(
                    f"DEBUG: No shared data returned for query_id {query_id}"
                )
                return

            logger.info(
                f"DEBUG: Shared data updated successfully for query_id {query_id}"
            )

            logger.info(
                f"DEBUG: Checking completion - agent_type={agent_type}, status={task_update_message.status}"
            )
            if agent_type == "chat_agent" and task_update_message.status == "done":
                logger.info(
                    f"DEBUG: ChatAgent completion detected! Triggering final completion for {query_id}"
                )
                await self._handle_final_completion(query_id, task_update_message)
            elif shared_data.status == TaskStatus.DONE and agent_type != "chat_agent":
                logger.info(
                    f"DEBUG: All non-chat tasks done, triggering ChatAgent for {query_id}"
                )
                await self._handle_trigger_chat_agent(query_id, shared_data)
            else:
                logger.info(
                    f"DEBUG: No action needed - shared_data.status={shared_data.status}, agent_type={agent_type}"
                )

        except Exception as e:
            logger.error(f"Task update failed for {query_id}: {e}")

    def _extract_agent_type_from_update(self, task_update: TaskUpdate) -> str:
        """Extract agent type from task update message.

        Args:
                task_update: TaskUpdate message

        Returns:
                str: The agent type that sent this update
        """
        if task_update.agent_type:
            return task_update.agent_type

        if task_update.results:
            for key in task_update.results.keys():
                if "inventory" in str(key).lower():
                    return "inventory_agent"
                elif "forecast" in str(key).lower():
                    return "forecasting_agent"
                elif "order" in str(key).lower():
                    return "ordering_agent"
                elif "chat" in str(key).lower() or "response" in str(key).lower():
                    return "chat_agent"

        logger.warning(f"Could not extract agent type from update: {task_update}")
        return ""

    async def _update_shared_data_atomic(
        self, query_id: str, agent_type: str, task_update: TaskUpdate
    ) -> Optional[SharedData]:
        """Enhanced atomic update with ChatAgent task injection."""
        shared_key = RedisKeys.get_shared_data_key(query_id)

        try:
            current_data = await self.redis.json().get(shared_key)
            if not current_data:
                logger.warning(f"No shared data for query {query_id}")
                return None

            shared_data = SharedData(**current_data)

            if (
                agent_type not in shared_data.task_graph.nodes
                and agent_type != "chat_agent"
            ):
                logger.error(
                    f"Agent {agent_type} not in task graph for query {query_id}"
                )
                return None

            if (
                agent_type == "chat_agent"
                and "chat_agent" not in shared_data.task_graph.nodes
            ):
                from src.typing.schema.orchestrator import TaskNode

                chat_task = TaskNode(
                    task_id="chat_1",
                    task_status="completed",  # Mark as completed since we're processing completion
                    agent_type="chat_agent",
                    sub_query=task_update.sub_query or "Generate final response",
                    dependencies=[],  # ChatAgent has no dependencies when triggered
                )

                shared_data.task_graph.nodes["chat_agent"] = [chat_task]
                logger.info(f"Added ChatAgent task to graph for query {query_id}")

            if agent_type not in shared_data.agents_done:
                shared_data.agents_done.append(agent_type)

            if task_update.results:
                shared_data.results[agent_type] = task_update.results
            if task_update.context:
                shared_data.context[agent_type] = task_update.context
            if task_update.llm_usage:
                shared_data.llm_usage[agent_type] = task_update.llm_usage

            if set(shared_data.agents_done) >= set(shared_data.agents_needed):
                shared_data.status = TaskStatus.DONE

            await update_shared_data(self.redis, query_id, shared_data)

            logger.info(f"Updated shared data for {agent_type} on query {query_id}")
            return shared_data

        except Exception as e:
            logger.error(f"Atomic shared data update failed for {query_id}: {e}")
            return None

    def _update_graph_status(
        self, shared_data: SharedData, agent_type: str, task_update: TaskUpdate
    ):
        """Update task completion in simplified graph structure."""
        if agent_type not in shared_data.task_graph.nodes:
            logger.warning(f"Agent {agent_type} not found in task graph")
            return

        for task in shared_data.task_graph.nodes[agent_type]:
            if hasattr(task_update, "task_id") and task.task_id == task_update.task_id:
                break
            elif task.sub_query in str(task_update.sub_query):
                break

    async def _handle_final_completion(
        self, query_id: str, chat_completion: TaskUpdate = None
    ):
        logger.info(f"Final completion for query {query_id}")

        final_response_data = None
        if chat_completion and chat_completion.results:
            final_response_data = chat_completion.results.get("final_response")

        await self._publish_final_completion(query_id, final_response_data)

    async def _handle_trigger_chat_agent(self, query_id: str, shared_data: SharedData):
        logger.info(f"All tasks done for query {query_id}, triggering ChatAgent")

        try:
            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_done,
                "results": shared_data.results,
                "key_metrics": self._extract_key_metrics(shared_data.context),
            }

            chat_message = {
                "command": "execute",
                "query_id": query_id,
                "sub_query": {
                    "query": "Generate final response from completed analysis",
                    "context": filtered_context,
                },
            }

            chat_channel = RedisChannels.get_command_channel("chat_agent")
            await self.redis.publish(chat_channel, json.dumps(chat_message))

            logger.info(f"Successfully triggered ChatAgent for query {query_id}")

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {query_id}: {e}")
            await self._publish_final_completion(
                query_id, {"error": "ChatAgent trigger failed", "fallback": True}
            )

    def _extract_key_metrics(self, context: Dict[str, Any]) -> Dict[str, Any]:
        metrics = {}

        for agent_type, agent_context in context.items():
            if isinstance(agent_context, dict):
                for key, value in agent_context.items():
                    if isinstance(value, (int, float)) or key in [
                        "stock_level",
                        "demand",
                        "revenue",
                        "count",
                        "total",
                        "amount",
                    ]:
                        metrics[f"{agent_type}_{key}"] = value

        return metrics

    def _filter_context_for_chat(self, shared_data: SharedData) -> Dict[str, Any]:
        try:
            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_done,
                "summary": {},
                "key_results": {},
                "metrics": {},
                "context_size_info": {},
            }

            for agent_type in shared_data.agents_done:
                agent_results = shared_data.results.get(agent_type, {})
                agent_context = shared_data.context.get(agent_type, {})

                key_results = {}
                for sub_query, result in agent_results.items():
                    if isinstance(result, str):
                        key_results[sub_query] = (
                            result[:500] + "..." if len(result) > 500 else result
                        )
                    else:
                        key_results[sub_query] = str(result)[:500]

                filtered_context["key_results"][agent_type] = key_results

                metrics = {}
                for sub_query, ctx in agent_context.items():
                    if isinstance(ctx, dict):
                        for key, value in ctx.items():
                            if isinstance(value, (int, float)):
                                metrics[f"{agent_type}_{key}"] = value
                            elif key in [
                                "stock_level",
                                "demand",
                                "revenue",
                                "count",
                                "total",
                                "amount",
                            ]:
                                metrics[f"{agent_type}_{key}"] = value

                filtered_context["metrics"].update(metrics)

                filtered_context["context_size_info"][agent_type] = {
                    "results_count": len(agent_results),
                    "context_items": len(agent_context),
                }

            return filtered_context

        except Exception as e:
            logger.error(f"Context filtering failed: {e}")
            return {
                "original_query": getattr(shared_data, "original_query", ""),
                "agents_completed": getattr(shared_data, "agents_done", []),
                "error": "Context filtering failed",
            }

    async def _publish_final_completion(
        self, query_id: str, final_response: dict = None
    ):
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data = await self.redis.json().get(shared_key)

            if shared_data:
                shared_data_obj = SharedData(**shared_data)

                llm_usage_serializable = {}
                for agent_type, usage in shared_data_obj.llm_usage.items():
                    if hasattr(usage, "model_dump"):
                        llm_usage_serializable[agent_type] = usage.model_dump()
                    else:
                        llm_usage_serializable[agent_type] = usage

                completion_data = {
                    "query_id": query_id,
                    "results": shared_data_obj.results,
                    "context": shared_data_obj.context,
                    "llm_usage": llm_usage_serializable,
                    "agents_done": shared_data_obj.agents_done,
                    "status": "completed",
                    "final_response": final_response,
                    "timestamp": datetime.now().isoformat(),
                }

                completion_channel = f"query:completion:{query_id}"
                await self.redis.publish(
                    completion_channel, json.dumps(completion_data)
                )

                logger.info(f"Published final completion with response for {query_id}")
            else:
                logger.error(f"No shared data found for final completion of {query_id}")

        except Exception as e:
            logger.error(f"Failed to publish final completion for {query_id}: {e}")

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)
        logger.info(f"{self.agent_type} listening on channels {channels}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        channel = message["channel"]

                        logger.info(
                            f"DEBUG: OrchestratorAgent received message on channel {channel}"
                        )
                        logger.info(f"DEBUG: Message data keys: {list(data.keys())}")
                        logger.info(f"DEBUG: Message data: {data}")

                        if channel == RedisChannels.TASK_UPDATES:
                            required_fields = [
                                "query_id",
                                "sub_query",
                                "status",
                                "results",
                                "llm_usage",
                            ]
                            missing_fields = [
                                field for field in required_fields if field not in data
                            ]

                            logger.info(f"DEBUG: Required fields: {required_fields}")
                            logger.info(f"DEBUG: Missing fields: {missing_fields}")

                            if missing_fields:
                                logger.error(
                                    f"Invalid TaskUpdate message missing fields {missing_fields}: {data}"
                                )
                                continue

                            if not isinstance(data.get("sub_query"), str):
                                logger.warning(
                                    f"Converting non-string sub_query to string: {data.get('sub_query')}"
                                )
                                data["sub_query"] = str(data.get("sub_query", ""))

                            data.setdefault("results", {})
                            data.setdefault("context", {})
                            data.setdefault("llm_usage", {})

                            logger.info(
                                f"DEBUG: About to parse TaskUpdate with data keys: {list(data.keys())}"
                            )

                            parsed_message = TaskUpdate(**data)

                            logger.info(
                                "DEBUG: Successfully parsed TaskUpdate, calling handle_task_update_message"
                            )

                            await self.handle_task_update_message(
                                channel=channel, task_update_message=parsed_message
                            )

                            logger.info(
                                f"DEBUG: Completed handle_task_update_message for query_id {parsed_message.query_id}"
                            )
                        else:
                            logger.warning(
                                f"OrchestratorAgent: Unknown channel {channel}"
                            )

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in message: {e}")
                    except Exception as e:
                        logger.error(f"{self.agent_type} message processing error: {e}")
                        logger.debug(f"Problematic message data: {data}")

        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in self.get_pub_channels():
            raise ValueError(f"OrchestratorAgent cannot publish to {channel}")

        try:
            if not isinstance(message, QueryTask):
                message = QueryTask(**message)
            await self.redis.publish(channel=channel, message=message.model_dump_json())

            logger.info(f"{self.agent_type} published on {channel}: {message}")
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def process(self, request: Request) -> OrchestratorResponse:
        try:
            if not request.query:
                raise ValueError("Query is required")

            history = await self._get_conversation_history(request.conversation_id)

            messages = [
                {"role": "system", "content": self.prompt},
                *history,
                {"role": "user", "content": request.query},
            ]

            response_content = await self._call_llm(
                messages=messages,
                response_schema=OrchestratorSchema,
                response_model=OrchestratorResponse,
            )
            logger.debug(f"Orchestrator LLM response: {response_content}")
            if request.conversation_id:
                await self._save_conversation_message(
                    request.conversation_id,
                    "user",
                    request.query,
                    {"query_id": request.query_id},
                )

            if response_content is None:
                return

            return OrchestratorResponse(
                query_id=request.query_id,
                agents_needed=response_content.agents_needed,
                task_dependency=response_content.task_dependency,
                llm_usage=getattr(response_content, "llm_usage", None),
                llm_reasoning=getattr(response_content, "llm_reasoning", None),
                error=None,
            )

        except Exception as e:
            logger.exception("OrchestratorAgent process failed: %s", e)
            return

    async def _get_conversation_history(self, conversation_id: str) -> List[Message]:
        try:
            LIMIT_CONTEXT_MESSAGES = 20
            if not conversation_id or not isinstance(conversation_id, str):
                logger.warning("Invalid conversation_id provided")
                return []

            key = f"conversation:{conversation_id}"
            message_raw = await self.redis.lrange(key, -LIMIT_CONTEXT_MESSAGES, -1)

            if not message_raw:
                return []

            conversation = ConversationData(conversation_id=conversation_id)
            for msg_raw in message_raw:
                if not isinstance(msg_raw, (str, bytes)):
                    continue

                msg_data = json.loads(msg_raw)
                conversation.messages.append(Message(**msg_data))

            return [
                {"role": msg.role, "content": msg.content}
                for msg in conversation.messages
            ]
        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []

    async def _save_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        try:
            if not conversation_id or not isinstance(conversation_id, str):
                logger.warning("Invalid conversation_id provided")
                return

            key = f"conversation:{conversation_id}"
            existing_data = await self.redis.get(key)

            if existing_data:
                data = json.loads(existing_data)
                conversation = ConversationData(**data)
            else:
                conversation = ConversationData(conversation_id=conversation_id)

            conversation.add_message(role=role, content=content, metadata=metadata)
            await self.redis.set(key, conversation.model_dump_json())

        except Exception as e:
            logger.error(f"Failed to save conversation message: {e}")

    async def start(self):
        logger.info("OrchestratorAgent: Starting workflow orchestration")
        await self.listen_channels()
