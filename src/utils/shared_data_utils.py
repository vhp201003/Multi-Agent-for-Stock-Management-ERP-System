import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis
from redis.commands.json.path import Path

from src.typing.redis import SharedData
from src.typing.redis.constants import RedisKeys
from src.utils.agent_helpers import validate_string_param

logger = logging.getLogger(__name__)


async def get_shared_data(
    redis_client: redis.Redis, query_id: str
) -> Optional[SharedData]:
    try:
        validate_string_param(query_id, "query_id")

        shared_data_key = RedisKeys.get_shared_data_key(query_id)
        data = await redis_client.json().get(shared_data_key)
        if data is None:
            return None
        return SharedData(**data)
    except (TypeError, ValueError) as e:
        logger.error(f"Error parsing shared data for {query_id}: {e}")
        return None


async def save_shared_data(
    redis_client: redis.Redis, query_id: str, shared_data: SharedData
):
    if not isinstance(shared_data, SharedData):
        raise ValueError("shared_data must be SharedData instance")

    key = RedisKeys.get_shared_data_key(query_id)

    try:
        await redis_client.json().set(key, Path.root_path(), shared_data.model_dump())
    except redis.RedisError:
        raise


async def update_shared_data(
    redis_client: redis.Redis, query_id: str, update_data: SharedData
):
    key = RedisKeys.get_shared_data_key(query_id)

    try:
        existing_data = await redis_client.json().get(key)

        if existing_data:
            try:
                existing_shared_data = SharedData(**existing_data)
            except (TypeError, ValueError) as e:
                logger.warning(f"Corrupted shared data for {query_id}, resetting: {e}")
                existing_shared_data = SharedData(
                    original_query="",
                    agents_needed=[],
                    sub_queries={},
                    agents_done=[],
                    results={},
                    context={},
                    llm_usage={},
                    status="processing",
                    task_graph=None,
                )

            merged_data = _merge_shared_data(existing_shared_data, update_data)
            validated = SharedData(**merged_data)
            await redis_client.json().set(key, Path.root_path(), validated.model_dump())
        else:
            await save_shared_data(redis_client, query_id, update_data)

    except redis.RedisError as e:
        logger.error(f"Redis error updating shared data for {query_id}: {e}")
        raise


def _merge_shared_data(existing: SharedData, update: SharedData) -> Dict[str, Any]:
    existing_dict = existing.model_dump()
    update_dict = update.model_dump()

    _deep_update(existing_dict, update_dict)
    return existing_dict


def _deep_update(current_data: Dict[str, Any], update_data: Dict[str, Any]) -> None:
    for key, value in update_data.items():
        if (
            key == "agents_done"
            and isinstance(value, list)
            and key in current_data
            and isinstance(current_data[key], list)
        ):
            existing_agents = set(current_data["agents_done"])
            for item in value:
                if item not in existing_agents:
                    current_data[key].append(item)
                    existing_agents.add(item)
        elif (
            isinstance(value, dict)
            and key in current_data
            and isinstance(current_data[key], dict)
        ):
            _deep_update(current_data[key], value)
        else:
            current_data[key] = value


async def get_shared_data_field(
    redis_client: redis.Redis, query_id: str, json_path: str
) -> Any:
    validate_string_param(json_path, "json_path")

    key = RedisKeys.get_shared_data_key(query_id)

    try:
        return await redis_client.json().get(key, Path(json_path))
    except redis.RedisError as e:
        logger.error(f"Redis error getting field {json_path} for {query_id}: {e}")
        raise


async def update_shared_data_field(
    redis_client: redis.Redis, query_id: str, json_path: str, value: Any
):
    validate_string_param(json_path, "json_path")

    key = RedisKeys.get_shared_data_key(query_id)

    try:
        await redis_client.json().set(key, Path(json_path), value)

    except redis.RedisError as e:
        logger.error(f"Redis error updating field {json_path} for {query_id}: {e}")
        raise


# ==================== TASK UTILITIES ====================


async def find_task_id(
    redis_client: redis.Redis,
    query_id: str,
    agent_type: str,
    sub_query: str,
) -> Optional[str]:
    """Find task_id from SharedData by agent_type and sub_query."""
    try:
        shared = await get_shared_data(redis_client, query_id)
        if not shared:
            return None
        return shared.get_task_id_by_sub_query(agent_type, sub_query)
    except Exception as e:
        logger.error(f"Task ID resolution failed for {query_id}: {e}")
        return None


async def get_dependency_context(
    redis_client: redis.Redis,
    query_id: str,
    task_id: str,
) -> Optional[str]:
    """Load results from completed dependency tasks and format for LLM context."""
    try:
        shared = await get_shared_data(redis_client, query_id)
        if not shared:
            return None

        dep_results = shared.get_dependency_results(task_id)
        if not dep_results:
            return None

        dep_results = truncate_results(dep_results, max_items=50, max_depth=4)
        return dep_results

    except Exception as e:
        logger.error(f"Failed to load dependency results for {task_id}: {e}")
        return None


def truncate_results(
    data: Any,
    max_items: int = 10,
    max_depth: int = 5,
    _current_depth: int = 0,
) -> Any:
    """Recursively filter/truncate nested data for LLM context.

    - Dict: recurse into values (up to max_depth)
    - List: take up to max_items elements, recurse if elements are dict/list
    - Other types: include as-is

    Args:
        data: Data to truncate (dict, list, or other)
        max_items: Max items per list
        max_depth: Max recursion depth
        _current_depth: Internal depth tracker

    Returns:
        Truncated data safe for LLM context
    """
    if not data:
        return {} if isinstance(data, dict) else data

    if _current_depth > max_depth:
        return {"_truncated": True}

    if isinstance(data, dict):
        filtered = {}
        for key, value in data.items():
            if isinstance(value, dict):
                filtered[key] = truncate_results(
                    value, max_items, max_depth, _current_depth + 1
                )
            elif isinstance(value, list):
                filtered[key] = _truncate_list(
                    value, max_items, max_depth, _current_depth
                )
            else:
                filtered[key] = value
        return filtered

    if isinstance(data, list):
        return _truncate_list(data, max_items, max_depth, _current_depth)

    return data


def _truncate_list(
    items: list,
    max_items: int,
    max_depth: int,
    current_depth: int,
) -> list:
    """Helper to truncate list items."""
    filtered_list = []
    for item in items[:max_items]:
        if isinstance(item, dict):
            filtered_list.append(
                truncate_results(item, max_items, max_depth, current_depth + 1)
            )
        elif isinstance(item, list):
            filtered_list.append(
                _truncate_list(item, max_items, max_depth, current_depth + 1)
            )
        else:
            filtered_list.append(item)

    if len(items) > max_items:
        filtered_list.append({"_truncated": True, "total_items": len(items)})

    return filtered_list
