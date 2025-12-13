"""
Agent Helper Utilities

Common patterns and utilities used across all agents to reduce code duplication.
Includes pub/sub listeners, validation, LLM response parsing, and data traversal.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ==================== PUB/SUB UTILITIES ====================


async def listen_pubsub_channels(
    redis,
    channels: List[str],
    message_handler: Callable[[str, bytes], Awaitable[None]],
    running_flag: Optional[Callable[[], bool]] = None,
):
    """Generic pub/sub listener with automatic channel routing and cleanup.

    This helper eliminates duplicate pub/sub subscription code across agents.
    Handles subscription, message routing, error recovery, and cleanup.

    Args:
        redis: Async Redis client
        channels: List of channel names to subscribe to
        message_handler: Async callback(channel_name: str, data: bytes)
            Called for each message received. Should handle JSON parsing.
        running_flag: Optional callable returning bool for loop control
            If provided, loop continues while running_flag() returns True.
            If None, runs indefinitely until exception.

    Example:
        async def handler(channel: str, data: bytes):
            if channel == "query":
                msg = QueryTask.model_validate_json(data)
                await process_query(msg)

        await listen_pubsub_channels(
            redis,
            ["query", "updates"],
            handler,
            lambda: self._running
        )
    """
    while running_flag() if running_flag else True:
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(*channels)

            async for msg in pubsub.listen():
                if running_flag and not running_flag():
                    break

                if msg["type"] != "message":
                    continue

                channel = msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                await message_handler(channel, msg["data"])

        except Exception as e:
            logger.error(f"Pub/sub listener error on {channels}: {e}")
            await asyncio.sleep(1)

        finally:
            try:
                await pubsub.unsubscribe(*channels)
                await pubsub.aclose()
            except Exception:
                pass


# ==================== VALIDATION UTILITIES ====================


def validate_string_param(value: Any, param_name: str) -> None:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{param_name} must be non-empty string")


def validate_dict_param(value: Any, param_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{param_name} must be dictionary")


# ==================== LLM RESPONSE PARSING ====================


def extract_llm_usage(response) -> Optional[Dict[str, Any]]:
    raw_usage = getattr(response, "usage", None)
    if not raw_usage:
        return None

    return {
        "completion_tokens": getattr(raw_usage, "completion_tokens", None),
        "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
        "total_tokens": getattr(raw_usage, "total_tokens", None),
        "completion_time": getattr(raw_usage, "completion_time", None),
        "prompt_time": getattr(raw_usage, "prompt_time", None),
        "queue_time": getattr(raw_usage, "queue_time", None),
        "total_time": getattr(raw_usage, "total_time", None),
    }


# ==================== DATA TRAVERSAL ====================


def traverse_full_data(full_data: Dict[str, Any]):
    if not isinstance(full_data, dict):
        return

    for agent_type, agent_tools in full_data.items():
        if not isinstance(agent_tools, dict):
            continue

        for tool_name, tool_result in agent_tools.items():
            yield agent_type, tool_name, tool_result


def find_first_array_in_dict(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(data, dict):
        return None

    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            logger.debug(f"Found data array: '{key}' ({len(value)} items)")
            return value

    return None
