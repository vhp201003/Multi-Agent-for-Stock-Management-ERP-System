import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts import build_orchestrator_prompt

from src.typing.redis import (
    ConversationData,
    QueryTask,
    RedisChannels,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.redis.constants import RedisKeys
from src.typing.request import Request
from src.typing.response import OrchestratorResponse
from src.typing.schema import OrchestratorSchema

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "OrchestratorAgent"):
        super().__init__(name)
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def handle_task_update_message(
        self, channel: str, task_update_message: TaskUpdate
    ):
        if not channel.startswith(RedisChannels.TASK_UPDATES):
            logger.warning(f"OrchestratorAgent: Ignoring invalid channel: {channel}")
            return

        try:
            agent_name = channel.split(":")[-1]
            query_id = task_update_message.query_id

            if not query_id:
                logger.error("OrchestratorAgent: Missing query_id in task update")
                return

            logger.info(
                f"OrchestratorAgent: Processing completion from {agent_name} for {query_id}"
            )

            shared_key = RedisKeys.get_shared_data_key(query_id)
            current_data_raw = await self.redis.get(shared_key)

            graph_update = {}
            if current_data_raw:
                try:
                    current_data = json.loads(current_data_raw)
                    current_shared = SharedData(**current_data)
                    graph_update = current_shared.graph.model_dump()

                    if agent_name in graph_update.get("nodes", {}):
                        agent_node = graph_update["nodes"][agent_name]
                        for sub_query_node in agent_node.get("sub_queries", []):
                            if sub_query_node["query"] == task_update_message.sub_query:
                                sub_query_node["status"] = task_update_message.status
                                break

                except Exception as e:
                    logger.warning(
                        f"OrchestratorAgent: Failed to load graph for update: {e}"
                    )

            are_all_tasks_done = self._are_all_tasks_done(graph_update)

            update_data = SharedData(
                agents_done=[agent_name],
                results={agent_name: task_update_message.results},
                context={agent_name: task_update_message.context},
                llm_usage={agent_name: task_update_message.llm_usage},
                graph=graph_update,
            )

            if are_all_tasks_done:
                update_data.status = TaskStatus.DONE

            await self.update_shared_data(query_id, update_data)

            if are_all_tasks_done:
                logger.info(
                    f"All tasks completed for query {query_id}, triggering ChatAgent"
                )

                # Get updated shared data for ChatAgent
                shared_key = RedisKeys.get_shared_data_key(query_id)
                updated_data_raw = await self.redis.get(shared_key)
                if updated_data_raw:
                    updated_shared_data = SharedData(**json.loads(updated_data_raw))
                    await self._trigger_chat_agent(query_id, updated_shared_data)
                else:
                    logger.warning(
                        f"No shared data found for completed query {query_id}"
                    )

        except Exception as e:
            logger.exception(f"OrchestratorAgent: Shared data update failed: {e}")

    def _are_all_tasks_done(self, graph: Dict[str, Any]) -> bool:
        if not graph or "nodes" not in graph:
            return False

        for agent_node in graph["nodes"].values():
            if "sub_queries" not in agent_node:
                continue
            for sub_query in agent_node["sub_queries"]:
                if sub_query.get("status") != TaskStatus.DONE:
                    return False
        return True

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
            for agent_name in shared_data.agents_done:
                agent_results = shared_data.results.get(agent_name, {})
                agent_context = shared_data.context.get(agent_name, {})

                # Extract key results (first 500 chars per result)
                key_results = {}
                for sub_query, result in agent_results.items():
                    if isinstance(result, str):
                        key_results[sub_query] = (
                            result[:500] + "..." if len(result) > 500 else result
                        )
                    else:
                        key_results[sub_query] = str(result)[:500]

                filtered_context["key_results"][agent_name] = key_results

                # Extract metrics and numbers from context
                metrics = {}
                for sub_query, ctx in agent_context.items():
                    if isinstance(ctx, dict):
                        # Extract numeric values and important fields
                        for key, value in ctx.items():
                            if isinstance(value, (int, float)):
                                metrics[f"{agent_name}_{key}"] = value
                            elif key in [
                                "stock_level",
                                "demand",
                                "revenue",
                                "count",
                                "total",
                                "amount",
                            ]:
                                metrics[f"{agent_name}_{key}"] = value

                filtered_context["metrics"].update(metrics)

                # Add context size info
                filtered_context["context_size_info"][agent_name] = {
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
                "timestamp": shared_data.created_at,
            }

            # Publish to ChatAgent command channel
            chat_command_channel = RedisChannels.get_command_channel("chat_agent")
            await self.redis.publish(chat_command_channel, json.dumps(chat_message))

            logger.info(
                f"Triggered ChatAgent for query {query_id} with filtered context"
            )

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {query_id}: {e}")

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
            for agent_name in shared_data.agents_done:
                agent_results = shared_data.results.get(agent_name, {})
                agent_context = shared_data.context.get(agent_name, {})

                # Extract key results (first 500 chars per result)
                key_results = {}
                for sub_query, result in agent_results.items():
                    if isinstance(result, str):
                        key_results[sub_query] = (
                            result[:500] + "..." if len(result) > 500 else result
                        )
                    else:
                        key_results[sub_query] = str(result)[:500]

                filtered_context["key_results"][agent_name] = key_results

                # Extract metrics and numbers from context
                metrics = {}
                for sub_query, ctx in agent_context.items():
                    if isinstance(ctx, dict):
                        # Extract numeric values and important fields
                        for key, value in ctx.items():
                            if isinstance(value, (int, float)):
                                metrics[f"{agent_name}_{key}"] = value
                            elif key in [
                                "stock_level",
                                "demand",
                                "revenue",
                                "count",
                                "total",
                                "amount",
                            ]:
                                metrics[f"{agent_name}_{key}"] = value

                filtered_context["metrics"].update(metrics)

                # Add context size info
                filtered_context["context_size_info"][agent_name] = {
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
                "timestamp": shared_data.created_at,
            }

            # Publish to ChatAgent command channel
            chat_command_channel = RedisChannels.get_command_channel("chat_agent")
            await self.redis.publish(chat_command_channel, json.dumps(chat_message))

            logger.info(
                f"Triggered ChatAgent for query {query_id} with filtered context"
            )

        except Exception as e:
            logger.error(f"Failed to trigger ChatAgent for {query_id}: {e}")

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        # Use psubscribe for pattern matching agent:task_updates:*
        patterns = [f"{RedisChannels.TASK_UPDATES}:*"]
        await pubsub.psubscribe(*patterns)
        logger.info(f"{self.name} listening on patterns {patterns}")

        try:
            async for message in pubsub.listen():
                if message["type"] == "pmessage":  # Pattern subscription uses pmessage
                    try:
                        data = json.loads(message["data"])
                        channel = message["channel"]

                        if not channel.startswith(RedisChannels.TASK_UPDATES):
                            logger.warning(
                                f"{self.name}: Ignoring non-TaskUpdate channel: {channel}"
                            )
                            continue

                        parsed_message = TaskUpdate(**data)

                        await self.handle_task_update_message(
                            channel=channel, task_update_message=parsed_message
                        )
                    except Exception as e:
                        logger.error(f"{self.name} message processing error: {e}")

        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.punsubscribe(f"{RedisChannels.TASK_UPDATES}:*")

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in await self.get_pub_channels():
            raise ValueError(f"OrchestratorAgent cannot publish to {channel}")

        try:
            validated = QueryTask(**message)
            await self.redis.publish(
                channel=channel, message=validated.model_dump_json()
            )

            logger.info(f"{self.name} published on {channel}: {message}")
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def process(self, request: Request) -> OrchestratorResponse:
        try:
            if not request.query:
                raise ValueError("Query is required")

            history = (
                self._get_conversation_history(request.conversation_id)
                if request.conversation_id
                else []
            )

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

            await self._save_conversation_message(
                request.conversation_id,
                "user",
                request.query,
                {"query_id": request.query_id},
            )

            if response_content is None:
                return OrchestratorResponse(
                    query_id=request.query_id,
                    agent_needed=[],
                    sub_queries=[],
                    dependencies=[],
                    error="no_response_from_llm",
                )

            if hasattr(response_content, "agent_needed") and hasattr(
                response_content, "sub_queries"
            ):
                try:
                    response_content.query_id = request.query_id
                except Exception:
                    pass
                return response_content

            return OrchestratorResponse(
                query_id=request.query_id,
                agent_needed=[],
                sub_queries=[],
                dependencies=[],
                llm_usage=getattr(response_content, "llm_usage", None),
                llm_reasoning=getattr(response_content, "llm_reasoning", None),
                error=getattr(response_content, "error", "parse_error"),
            )

        except Exception as e:
            logger.exception("OrchestratorAgent process failed: %s", e)
            return OrchestratorResponse(
                query_id=request.query_id,
                agent_needed=[],
                sub_queries=[],
                dependencies=[],
                error=str(e),
            )

    # TODO: Move conversation methods to ChatAgent for better separation of concerns
    async def _get_conversation_history(
        self, conversation_id: str
    ) -> List[Dict[str, str]]:
        try:
            # Input validation
            if not conversation_id or not isinstance(conversation_id, str):
                logger.warning("Invalid conversation_id provided")
                return []

            key = f"conversation:{conversation_id}"
            data_raw = await self.redis.get(key)

            if data_raw:
                data = json.loads(data_raw)
                conversation = ConversationData(**data)
                return conversation.get_recent_messages(
                    limit=20
                )  # Limit for context window
            else:
                conversation = ConversationData(conversation_id=conversation_id)
                await self.redis.set(key, conversation.model_dump_json())
                return []

        except Exception as e:
            logger.warning(f"Failed to load conversation {conversation_id}: {e}")
            return []

    async def _save_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        try:
            # Input validation
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
