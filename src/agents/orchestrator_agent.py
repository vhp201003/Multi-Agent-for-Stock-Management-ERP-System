import json
import logging
from typing import Any, Dict, List, Optional

from config.prompts import build_orchestrator_prompt
from src.agents.chat_agent import AGENT_TYPE as CHAT_AGENT_TYPE
from src.typing.llm_response import OrchestratorResponse
from src.typing.redis import (
    CompletionResponse,
    QueryTask,
    RedisChannels,
    SharedData,
    TaskStatus,
    TaskUpdate,
)
from src.typing.redis.constants import MessageType
from src.typing.request import ChatRequest, Request
from src.typing.schema import OrchestratorSchema
from src.utils import get_shared_data, save_shared_data
from src.utils.agent_helpers import listen_pubsub_channels
from src.utils.converstation import (
    load_or_create_conversation,
)

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)

AGENT_TYPE = "orchestrator"


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_type=AGENT_TYPE)

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.QUERY_CHANNEL]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def process(self, request: Request) -> None:
        try:
            # Create minimal SharedData FIRST - before any LLM calls
            await self.init_shared_data(request)

            history = await self.get_conversation_history(request)
            messages = self.compose_llm_messages(request, history)
            orchestration_result = await self.run_llm_orchestration(request, messages)

            if (
                not orchestration_result.result.agents_needed
                or len(orchestration_result.result.agents_needed) == 0
            ):
                await self.route_to_chat_agent_directly(request)
                return

            await self.update_shared_state_with_tasks(request, orchestration_result)
            sub_query_dict = self.build_sub_query_dict(orchestration_result)
            if not sub_query_dict:
                raise ValueError("No valid sub-queries found for orchestration")

            await self.publish_orchestration_task(request, sub_query_dict)

            await self.publish_broadcast(
                RedisChannels.get_query_updates_channel(request.query_id),
                MessageType.ORCHESTRATOR,
                {
                    "agents_needed": list(sub_query_dict.keys()),
                    "task_dependency": orchestration_result.result.task_dependency,
                    "agent_type": "orchestrator",
                },
            )

        except Exception as e:
            logger.error(f"LLM orchestration failed: {e}")
            raise

    async def init_shared_data(self, request: Request) -> None:
        shared_data = SharedData(
            original_query=request.query,
            query_id=request.query_id,
            agents_needed=[],
            status="processing",
            conversation_id=request.conversation_id,
        )
        await save_shared_data(self.redis, request.query_id, shared_data)

    async def get_conversation_history(self, request: Request) -> List[Any]:
        if request.conversation_id:
            conversation = await load_or_create_conversation(
                self.redis, request.conversation_id
            )
            return conversation.get_recent_messages(limit=10)
        return []

    def compose_llm_messages(
        self, request: Request, history: List[Any]
    ) -> List[Dict[str, Any]]:
        prompt = build_orchestrator_prompt(OrchestratorSchema)
        return [
            {"role": "system", "content": prompt},
            *history,
            {"role": "user", "content": request.query},
        ]

    async def run_llm_orchestration(
        self, request: Request, messages: List[Dict[str, Any]]
    ) -> OrchestratorResponse:
        result, llm_usage, llm_reasoning = await self.call_llm(
            query_id=request.query_id,
            messages=messages,
            response_schema=OrchestratorSchema,
        )

        if result and hasattr(result, "reasoning_steps") and result.reasoning_steps:
            await self.broadcast_reasoning_steps(
                request.query_id, result.reasoning_steps
            )

        return OrchestratorResponse(
            query_id=request.query_id,
            conversation_id=request.conversation_id,
            result=result,
            llm_usage=llm_usage,
            llm_reasoning=llm_reasoning,
        )

    async def broadcast_reasoning_steps(
        self, query_id: str, reasoning_steps: List[Any]
    ) -> None:
        for i, step in enumerate(reasoning_steps):
            try:
                step_data = {
                    "step_number": i + 1,
                    "total_steps": len(reasoning_steps),
                    "step": step.step if hasattr(step, "step") else str(step),
                    "explanation": step.explanation
                    if hasattr(step, "explanation")
                    else "",
                    "conclusion": step.conclusion
                    if hasattr(step, "conclusion")
                    else "",
                    "agent_type": self.agent_type,
                }

                await self.publish_broadcast(
                    RedisChannels.get_query_updates_channel(query_id),
                    MessageType.THINKING,
                    step_data,
                )

            except Exception as e:
                logger.warning(f"Failed to broadcast reasoning step {i + 1}: {e}")

    async def route_to_chat_agent_directly(self, request: Request) -> None:
        try:
            empty_context = {
                "original_query": request.query,
                "agents_completed": [],
                "results": {},
            }

            chat_message = ChatRequest(
                query_id=request.query_id,
                conversation_id=request.conversation_id,
                query=request.query,
                context=empty_context,
            )

            chat_channel = RedisChannels.get_command_channel(CHAT_AGENT_TYPE)
            await self.publish_channel(chat_channel, chat_message, ChatRequest)

        except Exception as e:
            logger.error(f"Failed to route to ChatAgent for {request.query_id}: {e}")

            error_response = CompletionResponse.response_error(
                query_id=request.query_id,
                error=f"Failed to process simple query: {str(e)}",
                conversation_id=request.conversation_id,
            )

            completion_channel = RedisChannels.get_query_completion_channel(
                request.query_id
            )

            await self.publish_channel(
                completion_channel, error_response, CompletionResponse
            )

    async def update_shared_state_with_tasks(
        self, request: Request, orchestration_result: OrchestratorResponse
    ) -> None:
        shared_data = await get_shared_data(self.redis, request.query_id)
        if not shared_data:
            return

        shared_data.agents_needed = orchestration_result.result.agents_needed
        for (
            agent_type,
            task_list,
        ) in orchestration_result.result.task_dependency.items():
            for task in task_list:
                shared_data.add_task(task)

        await save_shared_data(self.redis, request.query_id, shared_data)

    def build_sub_query_dict(
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

    async def publish_orchestration_task(
        self, request: Request, sub_query_dict: Dict[str, List[str]]
    ):
        message = QueryTask(
            query_id=request.query_id,
            agents_needed=list(sub_query_dict.keys()),
            sub_query=sub_query_dict,
        )
        await self.publish_channel(RedisChannels.QUERY_CHANNEL, message, QueryTask)

    async def listen_channels(self):
        async def handler(channel: str, data: bytes):
            if channel == RedisChannels.TASK_UPDATES:
                task_update_message = TaskUpdate.model_validate_json(data)
                await self.handle_task_update(task_update_message)

        channels = await self.get_sub_channels()
        await listen_pubsub_channels(self.redis, channels, handler)

    async def handle_task_update(self, task_update_message: TaskUpdate):
        try:
            shared_data: SharedData = await self.update_shared_data_tasks(
                task_update_message
            )
            if not shared_data:
                return

            if task_update_message.agent_type == CHAT_AGENT_TYPE:
                await self.publish_final_completion(task_update_message)
            elif shared_data.is_complete:
                await self.trigger_chat_agent(shared_data)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
        except Exception as e:
            logger.error(f"Task update processing error: {e}")

    async def update_shared_data_tasks(
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

    async def trigger_chat_agent(self, shared_data: SharedData):
        logger.info(
            f"All tasks done for query {shared_data.query_id}, triggering ChatAgent"
        )

        try:
            all_results = {}

            for agent_type in shared_data.agents_needed:
                agent_results = shared_data.get_agent_results(agent_type)
                if agent_results:
                    all_results[agent_type] = agent_results

            context = {
                "original_query": shared_data.original_query,
                "agents_completed": shared_data.agents_needed,
                "results": all_results,
            }

            chat_message = ChatRequest(
                query_id=shared_data.query_id,
                conversation_id=shared_data.conversation_id,
                query=shared_data.original_query,
                context=context,
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

    async def start(self):
        logger.info("OrchestratorAgent: Starting workflow orchestration")
        await self.listen_channels()
