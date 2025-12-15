"""
Query handling service - Business logic for processing user queries.
Separates business logic from API endpoint handlers.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from src.agents.orchestrator_agent import OrchestratorAgent
from src.api.lifespan import agent_manager
from src.services.quick_actions import generate_quick_actions
from src.services.semantic_cache import semantic_cache
from src.services.summary import summarize_conversation
from src.typing import Request
from src.typing.redis import (
    CompletionResponse,
    RedisChannels,
    SharedData,
)
from src.typing.schema import ChatAgentSchema, LLMMarkdownField
from src.utils.converstation import save_conversation_message
from src.utils.shared_data_utils import get_shared_data

logger = logging.getLogger(__name__)


class QueryValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_query_request(request: Request) -> Optional[str]:
    if not request.query or not request.query.strip():
        return "Query cannot be empty"

    if len(request.query) > 10000:
        return "Query too long (max 10,000 characters)"

    if request.query_id and not re.match(r"^[a-zA-Z0-9_-]+$", request.query_id):
        return "Invalid query ID format (alphanumeric, underscore, hyphen only)"

    if request.conversation_id and not re.match(
        r"^[a-zA-Z0-9_-]+$", request.conversation_id
    ):
        return "Invalid conversation ID format (alphanumeric, underscore, hyphen only)"

    return None


def ensure_conversation_id(request: Request) -> Request:
    if not hasattr(request, "conversation_id") or not request.conversation_id:
        request.conversation_id = request.query_id
    return request


def is_cacheable_response(response_data: Dict[str, Any]) -> bool:
    # 1. Must have layout with content
    layout = response_data.get("layout")
    if not layout or not isinstance(layout, list) or len(layout) == 0:
        return False

    # 2. Must have full_data with agent results
    full_data = response_data.get("full_data")
    if not full_data or not isinstance(full_data, dict):
        return False

    # 3. Check for error indicators in markdown content
    error_indicators = ["error", "failed", "lỗi", "không thể", "unable to", "exception"]
    for field in layout:
        if isinstance(field, dict) and field.get("field_type") == "markdown":
            content = (field.get("content") or "").lower()
            if any(indicator in content for indicator in error_indicators):
                logger.debug("Response contains error indicator, not caching")
                return False

    # 4. At least one agent must have results
    has_valid_results = any(
        isinstance(agent_data, dict) and len(agent_data) > 0
        for agent_data in full_data.values()
    )

    return has_valid_results


async def wait_for_completion(query_id: str) -> ChatAgentSchema:
    completion_channel = RedisChannels.get_query_completion_channel(query_id)
    redis_client = agent_manager.redis_client
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(completion_channel)

    try:
        start_time = datetime.now().timestamp()
        max_wait_time = 300.0  # 5 minutes

        async for message in pubsub.listen():
            if message["type"] == "message":
                chat_result: ChatAgentSchema = ChatAgentSchema.model_validate_json(
                    message["data"]
                )
                return chat_result

            if (datetime.now().timestamp() - start_time) > max_wait_time:
                return ChatAgentSchema(
                    layout=[
                        LLMMarkdownField(
                            content="""
                            Sorry, the request timed out after waiting for 5 minutes.
                            Please try again or contact support if the issue persists.
                            """
                        )
                    ]
                )
    except Exception:
        return ChatAgentSchema(
            layout=[
                LLMMarkdownField(
                    content="""
                    An error occurred while waiting for the completion response.
                    Please try again later.
                    """
                )
            ]
        )
    finally:
        await pubsub.unsubscribe(completion_channel)
        await pubsub.aclose()


async def store_completion_metrics(shared_data: SharedData) -> None:
    try:
        redis_client = agent_manager.redis_client
        agent_results = {}

        for agent_type in shared_data.agents_needed:
            results = shared_data.get_agent_results(agent_type)
            if results:
                agent_results[agent_type] = results

        internal_metrics = {
            "query_id": shared_data.query_id,
            "agent_results": agent_results,
            "llm_usage": {},
        }

        for usage_key, llm_usage in shared_data.llm_usage.items():
            if hasattr(llm_usage, "model_dump"):
                internal_metrics["llm_usage"][usage_key] = llm_usage.model_dump()

        metrics_key = f"metrics:{shared_data.query_id}"
        await redis_client.json().set(metrics_key, "$", internal_metrics)
        await redis_client.expire(metrics_key, 86400)  # 24 hours

        logger.debug(f"Stored completion metrics for {shared_data.query_id}")

    except Exception as e:
        logger.error(f"Failed to store completion metrics: {e}")


async def save_to_conversation_history(
    conversation_id: str,
    user_query: str,
    response_data: Dict[str, Any],
    from_cache: bool = False,
) -> None:
    redis_client = agent_manager.redis_client

    content_dict = {k: v for k, v in response_data.items() if k != "full_data"}

    await save_conversation_message(
        redis_client,
        conversation_id,
        "user",
        user_query,
    )

    metadata = {"full_data": response_data.get("full_data")}
    if from_cache:
        metadata["from_cache"] = True

    await save_conversation_message(
        redis_client,
        conversation_id,
        "assistant",
        json.dumps(content_dict, ensure_ascii=False),
        metadata=metadata,
    )


async def process_cached_response(
    request: Request, cached_response: Dict[str, Any]
) -> Dict[str, Any]:
    logger.info(f"Semantic cache hit for query: {request.query[:50]}...")

    result = CompletionResponse.response_success(
        query_id=request.query_id,
        response=cached_response,
        conversation_id=request.conversation_id,
    )

    if request.conversation_id:
        await save_to_conversation_history(
            request.conversation_id,
            request.query,
            cached_response,
            from_cache=True,
        )
        await summarize_conversation(request.conversation_id)
        await generate_quick_actions(request.conversation_id)

    return result.model_dump()


async def process_new_query(request: Request) -> Dict[str, Any]:
    logger.info(f"Cache miss, processing query: {request.query[:50]}...")

    redis_client = agent_manager.redis_client
    orchestrator: OrchestratorAgent = agent_manager.agents.get("orchestrator")

    await orchestrator.process(request)
    chat_result: ChatAgentSchema = await wait_for_completion(request.query_id)
    chat_response_dict: dict = chat_result.model_dump()

    result = CompletionResponse.response_success(
        query_id=request.query_id,
        response=chat_response_dict,
        conversation_id=request.conversation_id,
    )

    # Save to conversation history
    if request.conversation_id:
        await save_to_conversation_history(
            request.conversation_id,
            request.query,
            chat_response_dict,
        )

    # Store metrics
    shared_data = await get_shared_data(redis_client, request.query_id)
    await store_completion_metrics(shared_data)

    # Post-processing
    await summarize_conversation(request.conversation_id)
    await generate_quick_actions(request.conversation_id)

    # Save to semantic cache (only if enabled AND response is valid)
    if request.use_cache and is_cacheable_response(chat_response_dict):
        await semantic_cache.save_to_cache(
            query_text=request.query,
            response_data=chat_response_dict,
            conversation_id=request.conversation_id,
            query_id=request.query_id,
        )
        logger.debug("Response passed validation, saved to cache")
    elif request.use_cache:
        logger.debug("Response failed validation, not caching")

    return result.model_dump()


async def handle_query(request: Request) -> Dict[str, Any]:
    """
    Main query handler - orchestrates the full query processing flow.

    Flow:
    1. Validate request
    2. Check semantic cache (if enabled)
    3. If cache hit: return cached response
    4. If cache miss or cache disabled: process through orchestrator
    5. Save results and return response
    """
    try:
        request = ensure_conversation_id(request)
        validation_error = validate_query_request(request)

        if validation_error:
            raise QueryValidationError(validation_error)

        # Only search cache if enabled
        if request.use_cache:
            cached_response = await semantic_cache.search_cache(request.query)
            if cached_response:
                return await process_cached_response(request, cached_response)

        # Cache miss or disabled - process normally
        return await process_new_query(request)

    except QueryValidationError:
        raise
    except Exception as e:
        result = CompletionResponse.response_error(
            query_id=request.query_id,
            error=f"Internal server error: {str(e)}",
            conversation_id=request.conversation_id,
        )
        logger.exception(f"Critical error processing query {request.query_id}: {e}")
        return result.model_dump()
