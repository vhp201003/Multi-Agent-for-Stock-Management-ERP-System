import logging
from typing import Any, Dict, Optional

import redis.asyncio as redis
from redis.commands.json.path import Path

from src.typing.redis import SharedData
from src.typing.redis.constants import RedisKeys

logger = logging.getLogger(__name__)


async def get_shared_data(
    redis_client: redis.Redis, query_id: str
) -> Optional[SharedData]:
    try:
        if not query_id or not isinstance(query_id, str):
            raise ValueError("query_id must be non-empty string")

        shared_data_key = RedisKeys.get_shared_data_key(query_id)
        data = await redis_client.json().get(shared_data_key)
        return SharedData.model_validate_json(data)
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
    if not json_path or not isinstance(json_path, str):
        raise ValueError("json_path must be non-empty string")

    key = RedisKeys.get_shared_data_key(query_id)

    try:
        return await redis_client.json().get(key, Path(json_path))
    except redis.RedisError as e:
        logger.error(f"Redis error getting field {json_path} for {query_id}: {e}")
        raise


async def update_shared_data_field(
    redis_client: redis.Redis, query_id: str, json_path: str, value: Any
):
    if not json_path or not isinstance(json_path, str):
        raise ValueError("json_path must be non-empty string")

    key = RedisKeys.get_shared_data_key(query_id)

    try:
        await redis_client.json().set(key, Path(json_path), value)

    except redis.RedisError as e:
        logger.error(f"Redis error updating field {json_path} for {query_id}: {e}")
        raise
