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
        self.prompt = build_orchestrator_prompt(OrchestratorSchema)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def process(self, request: Request) -> OrchestratorResponse:
        try:
            if not request.query:
                return OrchestratorResponse(
                    agents_needed=[],
                    task_dependency={"nodes": {}},
                    error="Query cannot be empty",
                )

            history = []
            if request.conversation_id:
                try:
                    conversation_key = RedisKeys.get_conversation_key(
                        request.conversation_id
                    )
                    conversation_data = await self.redis.json().get(conversation_key)
                    if conversation_data:
                        conversation = ConversationData(**conversation_data)
                        history = [
                            {"role": msg.role, "content": msg.content}
                            for msg in conversation.messages[-10:]
                        ]
                except Exception as e:
                    logger.warning(f"Failed to load conversation history: {e}")

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

            if request.conversation_id and response_content:
                try:
                    await self._save_conversation_message(
                        request.conversation_id, "user", request.query
                    )
                    await self._save_conversation_message(
                        request.conversation_id, "assistant", str(response_content)
                    )
                except Exception as e:
                    logger.warning(f"Failed to save conversation: {e}")

            if response_content is None:
                return OrchestratorResponse(
                    agents_needed=[],
                    task_dependency={"nodes": {}},
                    error="Failed to process query",
                )

            return (
                response_content
                if isinstance(response_content, OrchestratorResponse)
                else OrchestratorResponse(
                    agents_needed=[],
                    task_dependency={"nodes": {}},
                    error="Invalid response format",
                )
            )

        except Exception as e:
            logger.error(f"Orchestration failed: {e}")
            return OrchestratorResponse(
                agents_needed=[],
                task_dependency={"nodes": {}},
                error=f"Processing error: {str(e)[:100]}",
            )

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self._handle_task_update(message["channel"], message["data"])
        except Exception as e:
            logger.error(f"Redis error in listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def _handle_task_update(self, channel: str, raw_data: str):
        if channel != RedisChannels.TASK_UPDATES:
            logger.warning(f"OrchestratorAgent: Invalid channel: {channel}")
            return

        try:
            data = json.loads(raw_data)

            if not isinstance(data.get("sub_query"), str):
                data["sub_query"] = str(data.get("sub_query", ""))
            data.setdefault("results", {})
            data.setdefault("context", {})
            data.setdefault("llm_usage", {})

            task_update = TaskUpdate(**data)

            agent_type = task_update.agent_type
            if not agent_type and task_update.results:
                for key in task_update.results.keys():
                    if key in ["inventory", "forecasting", "ordering", "chat_agent"]:
                        agent_type = key
                        break

            query_id = task_update.query_id
            if not query_id:
                logger.error("Missing query_id in task update")
                return

            shared_data = await self._update_shared_data(
                query_id, agent_type, task_update
            )
            if not shared_data:
                return

            if agent_type == "chat_agent" and task_update.status == "done":
                await self._publish_final_completion(query_id, task_update)
            elif shared_data.status == TaskStatus.DONE and agent_type != "chat_agent":
                await self._trigger_chat_agent(query_id, shared_data)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
        except Exception as e:
            logger.error(f"Task update processing error: {e}")

    async def _update_shared_data(
        self, query_id: str, agent_type: str, task_update: TaskUpdate
    ) -> Optional[SharedData]:
        shared_key = RedisKeys.get_shared_data_key(query_id)

        try:
            current_data = await self.redis.json().get(shared_key)
            if not current_data:
                logger.warning(f"No shared data for query {query_id}")
                return None

            shared_data = SharedData(**current_data)

            if (
                agent_type == "chat_agent"
                and "chat_agent" not in shared_data.task_graph.nodes
            ):
                from src.typing.schema.orchestrator import TaskNode

                chat_task = TaskNode(
                    task_id="chat_1",
                    agent_type="chat_agent",
                    sub_query="Generate final response from completed analysis",
                    dependencies=[],
                )
                shared_data.task_graph.nodes["chat_agent"] = [chat_task]
                logger.info(f"Added ChatAgent task to graph for query {query_id}")

            if agent_type not in shared_data.agents_done:
                shared_data.agents_done.append(agent_type)

            if task_update.results:
                shared_data.results.update({agent_type: task_update.results})
            if task_update.context:
                shared_data.context.update({agent_type: task_update.context})
            if task_update.llm_usage:
                shared_data.llm_usage.update({agent_type: task_update.llm_usage})

            if set(shared_data.agents_done) >= set(shared_data.agents_needed):
                shared_data.status = TaskStatus.DONE

            await update_shared_data(self.redis, query_id, shared_data)
            logger.info(f"Updated shared data for {agent_type} on query {query_id}")
            return shared_data

        except Exception as e:
            logger.error(f"Atomic shared data update failed for {query_id}: {e}")
            return None

    async def _trigger_chat_agent(self, query_id: str, shared_data: SharedData):
        logger.info(f"All tasks done for query {query_id}, triggering ChatAgent")

        try:
            filtered_context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_done,
                "results": shared_data.results,
                "key_metrics": {},
            }

            for agent_type, agent_context in shared_data.context.items():
                if isinstance(agent_context, dict):
                    filtered_context["key_metrics"][agent_type] = {
                        k: v
                        for k, v in agent_context.items()
                        if k in ["total_items", "completion_rate", "processing_time"]
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

    async def _publish_final_completion(self, query_id: str, final_response_data=None):
        try:
            shared_key = RedisKeys.get_shared_data_key(query_id)
            shared_data = await self.redis.json().get(shared_key)

            if shared_data:
                shared_obj = SharedData(**shared_data)

                llm_usage_serialized = {}
                for agent_type, llm_usage in shared_obj.llm_usage.items():
                    if hasattr(llm_usage, "model_dump"):
                        llm_usage_serialized[agent_type] = llm_usage.model_dump()
                    elif isinstance(llm_usage, dict):
                        llm_usage_serialized[agent_type] = llm_usage
                    else:
                        llm_usage_serialized[agent_type] = {
                            attr: getattr(llm_usage, attr, None)
                            for attr in [
                                "completion_tokens",
                                "prompt_tokens",
                                "total_tokens",
                                "completion_time",
                                "prompt_time",
                                "queue_time",
                                "total_time",
                            ]
                            if hasattr(llm_usage, attr)
                        }

                completion_data = {
                    "query_id": query_id,
                    "status": "completed",
                    "final_response": final_response_data.get("final_response")
                    if isinstance(final_response_data, dict)
                    else None,
                    "results": shared_obj.results,
                    "context": shared_obj.context,
                    "llm_usage": llm_usage_serialized,
                    "agents_done": shared_obj.agents_done,
                    "timestamp": datetime.now().isoformat(),
                    "processing_time": None,
                    "execution_progress": shared_obj.execution_progress,
                }

                completion_channel = RedisChannels.get_query_completion_channel(
                    query_id
                )
                await self.redis.publish(
                    completion_channel, json.dumps(completion_data)
                )
                logger.info(f"Published final completion with response for {query_id}")
            else:
                fallback_data = {
                    "query_id": query_id,
                    "status": "completed",
                    "error": "Shared data unavailable for final completion",
                    "timestamp": datetime.now().isoformat(),
                }
                completion_channel = RedisChannels.get_query_completion_channel(
                    query_id
                )
                await self.redis.publish(completion_channel, json.dumps(fallback_data))

        except Exception as e:
            logger.error(f"Failed to publish final completion for {query_id}: {e}")

    async def _save_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        try:
            message = Message(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                metadata=metadata or {},
            )
            key = f"conversation:{conversation_id}"
            await self.redis.rpush(key, json.dumps(message.model_dump()))
            await self.redis.expire(key, 86400)  # 24 hours
        except Exception as e:
            logger.error(f"Failed to save conversation message: {e}")

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
