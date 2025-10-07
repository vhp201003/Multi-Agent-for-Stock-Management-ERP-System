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

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "OrchestratorAgent"


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_type=AGENT_TYPE)
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)
        self.completed_queries = set()  # Track queries that have been completed to avoid duplicate ChatAgent triggers

    def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def handle_task_update_message(
        self, channel: str, task_update_message: TaskUpdate
    ):
        """Simplified task update handler with atomic state transitions."""
        if not channel.startswith(RedisChannels.TASK_UPDATES):
            logger.warning(f"OrchestratorAgent: Invalid channel: {channel}")
            return

        agent_type = channel.split(":")[-1]
        query_id = task_update_message.query_id

        if not query_id:
            logger.error("Missing query_id in task update")
            return

        # Security: Prevent duplicate processing
        if query_id in self.completed_queries:
            logger.debug(f"Query {query_id} already completed")
            return

        try:
            # Single atomic update operation
            shared_data = await self._update_shared_data_atomic(
                query_id, agent_type, task_update_message
            )

            if not shared_data:
                return

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

    async def _update_shared_data_atomic(
        self, query_id: str, agent_type: str, task_update: TaskUpdate
    ) -> Optional[SharedData]:
        """Single atomic operation to update shared data."""
        shared_key = RedisKeys.get_shared_data_key(query_id)

        try:
            # Get current data
            current_data = await self.redis.json().get(shared_key)
            if not current_data:
                logger.warning(f"No shared data for query {query_id}")
                return None

            shared_data = SharedData(**current_data)

            # Update agent completion
            if agent_type not in shared_data.agents_done:
                shared_data.agents_done.append(agent_type)

            # Merge task results
            shared_data.results[agent_type] = task_update.results
            shared_data.context[agent_type] = task_update.context
            shared_data.llm_usage[agent_type] = task_update.llm_usage

            # Update graph status
            self._update_graph_status(shared_data, agent_type, task_update)

            # Check completion status - simplified approach
            completed_task_ids = set(
                task.task_id
                for agent_node in shared_data.task_graph.nodes.values()
                for task in agent_node.tasks
                if task.status == "done"
            )
            all_task_ids = set(
                task.task_id
                for agent_node in shared_data.task_graph.nodes.values()
                for task in agent_node.tasks
            )
            if completed_task_ids == all_task_ids and all_task_ids:
                shared_data.status = TaskStatus.DONE

            # Atomic persist
            await self.update_shared_data(query_id, shared_data)

            logger.info(f"Updated shared data for {agent_type} on query {query_id}")
            return shared_data

        except Exception as e:
            logger.error(f"Failed to update shared data atomically: {e}")
            return None

    def _update_graph_status(
        self, shared_data: SharedData, agent_type: str, task_update: TaskUpdate
    ):
        """Update graph node status for completed task."""
        if not shared_data.task_graph:
            return

        # Find and update the matching task
        for agent_node in shared_data.task_graph.nodes.values():
            for task in agent_node.tasks:
                if task.sub_query == task_update.sub_query:
                    task.status = task_update.status
                    break

    async def _handle_final_completion(
        self, query_id: str, chat_completion: TaskUpdate = None
    ):
        """Handle final completion when ChatAgent is done."""
        self.completed_queries.add(query_id)

        logger.info(f"Final completion for query {query_id}")

        # Include ChatAgent's final response in completion data
        final_response_data = None
        if chat_completion and chat_completion.results:
            final_response_data = chat_completion.results.get("final_response")

        await self._publish_final_completion(query_id, final_response_data)

    async def _handle_trigger_chat_agent(self, query_id: str, shared_data: SharedData):
        """Trigger ChatAgent when all tasks are done."""
        self.completed_queries.add(query_id)

        logger.info(f"All tasks done for query {query_id}, triggering ChatAgent")

        # Simple context filtering - FIXED: Ensure serializable data
        try:
            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_done,
                "results": shared_data.results,
                "key_metrics": self._extract_key_metrics(shared_data.context),
            }

            # Trigger ChatAgent with proper message structure
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
            # RESILIENCE: Create fallback completion to unblock main.py
            await self._publish_final_completion(
                query_id, {"error": "ChatAgent trigger failed", "fallback": True}
            )

    def _extract_key_metrics(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract numeric metrics from context for ChatAgent."""
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
        """Filter and summarize context data to avoid prompt overload."""
        try:
            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_done,
                "summary": {},
                "key_results": {},
                "metrics": {},
                "context_size_info": {},
            }

            # Process results and context for each agent
            for agent_type in shared_data.agents_done:
                agent_results = shared_data.results.get(agent_type, {})
                agent_context = shared_data.context.get(agent_type, {})

                # Extract key results (first 500 chars per result)
                key_results = {}
                for sub_query, result in agent_results.items():
                    if isinstance(result, str):
                        key_results[sub_query] = (
                            result[:500] + "..." if len(result) > 500 else result
                        )
                    else:
                        key_results[sub_query] = str(result)[:500]

                filtered_context["key_results"][agent_type] = key_results

                # Extract metrics and numbers from context
                metrics = {}
                for sub_query, ctx in agent_context.items():
                    if isinstance(ctx, dict):
                        # Extract numeric values and important fields
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

                # Add context size info
                filtered_context["context_size_info"][agent_type] = {
                    "results_count": len(agent_results),
                    "context_items": len(agent_context),
                }

            return filtered_context

        except Exception as e:
            logger.error(f"Context filtering failed: {e}")
            # Fallback to minimal context
            return {
                "original_query": getattr(shared_data, "original_query", ""),
                "agents_completed": getattr(shared_data, "agents_done", []),
                "error": "Context filtering failed",
            }

    async def _trigger_chat_agent(self, query_id: str, shared_data: SharedData):
        """Trigger ChatAgent to generate final response with filtered context."""
        try:
            # Filter context to avoid prompt overload
            filtered_context = self._filter_context_for_chat(shared_data)

            # Create chat request
            chat_message = {
                "command": "execute",
                "query_id": query_id,
                "sub_query": {
                    "query": "Generate comprehensive response based on completed analysis",
                    "context": filtered_context,
                },
            }

            # Publish to ChatAgent command channel
            chat_command_channel = RedisChannels.get_command_channel("chat_agent")
            await self.redis.publish(chat_command_channel, json.dumps(chat_message))

            logger.info(
                f"Triggered ChatAgent for query {query_id} with filtered context"
            )

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {query_id}: {e}")

    async def _publish_final_completion(
        self, query_id: str, final_response: dict = None
    ):
        """Publish final completion notification for main.py to return response."""
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data = await self.redis.json().get(shared_key)

            if shared_data:
                shared_data_obj = SharedData(**shared_data)

                completion_data = {
                    "query_id": query_id,
                    "results": shared_data_obj.results,
                    "context": shared_data_obj.context,
                    "llm_usage": shared_data_obj.llm_usage,
                    "agents_done": shared_data_obj.agents_done,
                    "status": "completed",
                    "final_response": final_response,  # 🎯 Include ChatAgent's response
                    "timestamp": datetime.now().isoformat(),
                }

                # 🚀 This is what handle_query waits for
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
        patterns = [f"{RedisChannels.TASK_UPDATES}:*"]
        await pubsub.psubscribe(*patterns)
        logger.info(f"{self.agent_type} listening on patterns {patterns}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        data = json.loads(message["data"])
                        channel = message["channel"]

                        logger.info(
                            f"DEBUG: OrchestratorAgent received message on channel {channel}"
                        )
                        logger.info(f"DEBUG: Message data keys: {list(data.keys())}")
                        logger.info(f"DEBUG: Message data: {data}")

                        if not channel.startswith(RedisChannels.TASK_UPDATES):
                            logger.warning(
                                f"{self.agent_type}: Ignoring non-TaskUpdate channel: {channel}"
                            )
                            continue

                        # SECURITY: Validate message structure before parsing
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

                        # PERFORMANCE: Type validation with fallbacks
                        if not isinstance(data.get("sub_query"), str):
                            logger.warning(
                                f"Converting non-string sub_query to string: {data.get('sub_query')}"
                            )
                            data["sub_query"] = str(data.get("sub_query", ""))

                        # Default required fields if missing
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

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in message: {e}")
                    except Exception as e:
                        logger.error(f"{self.agent_type} message processing error: {e}")
                        logger.debug(f"Problematic message data: {data}")

        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.punsubscribe(f"{RedisChannels.TASK_UPDATES}:*")

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
            logger.info(f"Orchestrator LLM response: {response_content}")
            if request.conversation_id:
                await self._save_conversation_message(
                    request.conversation_id,
                    "user",
                    request.query,
                    {"query_id": request.query_id},
                )

            if response_content is None:
                from src.typing.schema.orchestrator import TaskDependencyGraph

                return OrchestratorResponse(
                    query_id=request.query_id,
                    agents_needed=[],
                    task_dependency=TaskDependencyGraph(),
                    error="no_response_from_llm",
                )

            if hasattr(response_content, "agents_needed") and hasattr(
                response_content, "task_dependency"
            ):
                try:
                    return OrchestratorResponse(
                        query_id=request.query_id,
                        agents_needed=response_content.agents_needed,
                        task_dependency=response_content.task_dependency,
                        llm_usage=getattr(response_content, "llm_usage", None),
                        llm_reasoning=getattr(response_content, "llm_reasoning", None),
                        error=None,
                    )
                except Exception:
                    pass

            from src.typing.schema.orchestrator import TaskDependencyGraph

            return OrchestratorResponse(
                query_id=request.query_id,
                agents_needed=[],
                task_dependency=TaskDependencyGraph(),
                llm_usage=getattr(response_content, "llm_usage", None),
                llm_reasoning=getattr(response_content, "llm_reasoning", None),
                error=getattr(response_content, "error", "parse_error"),
            )

        except Exception as e:
            logger.exception("OrchestratorAgent process failed: %s", e)
            from src.typing.schema.orchestrator import TaskDependencyGraph

            return OrchestratorResponse(
                query_id=request.query_id,
                agents_needed=[],
                task_dependency=TaskDependencyGraph(),
                error=str(e),
            )

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

            # Filter message for role and content
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
