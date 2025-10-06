import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

import redis.asyncio as redis
from config.settings import DEFAULT_CONFIGS, AgentConfig
from dotenv import load_dotenv
from groq import AsyncGroq
from jsonschema import ValidationError
from redis.commands.json.path import Path

from src.typing import BaseAgentResponse, BaseSchema
from src.typing.redis import SharedData
from src.typing.redis.constants import RedisKeys

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        agent_type: str,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        llm_api_key: str = None,
        llm_model: str = "llama-3.3-70b-versatile",
    ):
        self.agent_type = agent_type
        self.redis = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )
        self.llm_api_key = llm_api_key or os.environ.get("GROQ_API_KEY")
        self.llm_model = llm_model
        self.config = DEFAULT_CONFIGS.get(self.agent_type, AgentConfig())
        self.llm = AsyncGroq(api_key=self.llm_api_key) if self.llm_api_key else None

    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        response_schema: Optional[Type[BaseSchema]] = None,
        response_model: Optional[Type[BaseAgentResponse]] = None,
    ) -> Any:
        """Call LLM with structured response parsing."""
        if not self.llm:
            raise ValueError("No Groq API key provided")
        try:
            response_format = None
            if response_schema:
                schema = response_schema.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": schema},
                }

            response = await self.llm.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                response_format=response_format,
            )

            logger.debug("LLM raw response: %s", response)
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            content = (
                message.content.strip() if getattr(message, "content", None) else None
            )
            llm_reasoning = getattr(message, "reasoning", None)

            raw_usage = getattr(response, "usage", None)
            if raw_usage:
                llm_usage = {
                    "completion_tokens": getattr(raw_usage, "completion_tokens", None),
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
                    "total_tokens": getattr(raw_usage, "total_tokens", None),
                    "completion_time": getattr(raw_usage, "completion_time", None),
                    "prompt_time": getattr(raw_usage, "prompt_time", None),
                    "queue_time": getattr(raw_usage, "queue_time", None),
                    "total_time": getattr(raw_usage, "total_time", None),
                }
            else:
                llm_usage = None

            if response_model:
                try:
                    data = json.loads(content) if content else {}
                    parsed = response_model.model_validate(data)
                    if hasattr(parsed, "llm_usage"):
                        parsed.llm_usage = llm_usage
                    if hasattr(parsed, "llm_reasoning"):
                        parsed.llm_reasoning = llm_reasoning
                    return parsed
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.exception("LLM parsing/validation error: %s", e)
                    debug = BaseAgentResponse()
                    debug.llm_usage = llm_usage
                    debug.llm_reasoning = llm_reasoning
                    debug.error = str(e) if hasattr(debug, "error") else None
                    return debug
        except Exception as e:
            logger.exception("LLM call failed: %s", e)
            return "LLM error: Unable to generate response"

    @abstractmethod
    async def get_pub_channels(self) -> List[str]:
        """Return list of channels this agent publishes to."""
        pass

    @abstractmethod
    async def get_sub_channels(self) -> List[str]:
        """Return list of channels this agent subscribes to."""
        pass

    @abstractmethod
    async def process(self, request) -> Any:
        """Process a request and return a response.

        Core business logic method that all agents must implement:
        - OrchestratorAgent: LLM-based query decomposition and coordination
        - WorkerAgent: Domain-specific task execution with MCP tools

        Args:
            request: Agent-specific request object

        Returns:
            Agent-specific response object
        """
        pass

    @abstractmethod
    async def listen_channels(self):
        """Listen to subscribed channels and process messages.

        Each agent implements channel-specific listening logic:
        - OrchestratorAgent: Listens for task updates and workflow coordination
        - WorkerAgent: Listens for execution commands

        Must handle message parsing, validation, and dispatch to update_shared_data_from_message.
        """
        pass

    @abstractmethod
    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        """Publish validated message to specified channel.

        Each agent implements channel-specific publishing logic:
        - OrchestratorAgent: Publishes query tasks to managers
        - WorkerAgent: Publishes task completion updates

        Args:
            channel: Target Redis channel
            message: Message data to publish (will be validated and serialized)
        """
        pass

    async def update_shared_data(self, query_id: str, update_shared_data: SharedData):
        """Update shared data by merging with existing SharedData instance using Redis JSON.

        Args:
            query_id: Unique identifier for the query
            update_shared_data: SharedData instance containing updates to merge

        Raises:
            ValueError: If query_id is invalid or update_shared_data is not SharedData
            Exception: For Redis or validation errors
        """
        if not query_id or not isinstance(query_id, str):
            raise ValueError("query_id must be non-empty string")
        if not isinstance(update_shared_data, SharedData):
            raise ValueError("update_shared_data must be SharedData instance")

        key = RedisKeys.get_shared_data_key(query_id)

        try:
            # Check if JSON document exists using Redis JSON
            existing_data = await self.redis.json().get(key)

            if existing_data:
                try:
                    existing_shared_data = SharedData(**existing_data)
                except (TypeError, ValueError) as e:
                    logger.warning(
                        f"Corrupted shared data for {query_id}, resetting: {e}"
                    )
                    existing_shared_data = SharedData(
                        original_query="",
                        agents_needed=[],
                        sub_queries={},
                        dependencies=[],
                        agents_done=[],
                        results={},
                        context={},
                        llm_usage={},
                        status="processing",
                        created_at="",
                        graph={"nodes": {}, "edges": []},
                    )

                merged_data = self._merge_shared_data(
                    existing_shared_data, update_shared_data
                )

                validated = SharedData(**merged_data)
                # Set the entire JSON document using Redis JSON
                await self.redis.json().set(
                    key, Path.root_path(), validated.model_dump()
                )

            else:
                logger.info(
                    f"No existing shared data for {query_id}, initializing with update"
                )
                # Set new JSON document
                await self.redis.json().set(
                    key, Path.root_path(), update_shared_data.model_dump()
                )

            logger.debug(
                f"Updated shared data for {query_id}: {update_shared_data.model_dump()}"
            )

        except redis.RedisError as e:
            logger.error(f"Redis error updating shared data for {query_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Shared data update failed for {query_id}: {e}")
            raise

    def _merge_shared_data(
        self, existing: SharedData, update: SharedData
    ) -> Dict[str, Any]:
        """Merge update SharedData into existing SharedData.

        Handles special merging logic for lists (agents_done) and nested dicts.

        Args:
            existing: Current SharedData from Redis
            update: New SharedData with updates

        Returns:
            Merged data dictionary ready for validation
        """
        existing_dict = existing.model_dump()
        update_dict = update.model_dump()

        self._deep_update(existing_dict, update_dict)

        return existing_dict

    def _deep_update(
        self, current_data: Dict[str, Any], update_data: Dict[str, Any]
    ) -> None:
        """Deep merge update_data into current_data with special handling.

        Args:
            current_data: Dictionary to update (modified in-place)
            update_data: Dictionary with updates to merge
        """
        if not isinstance(current_data, dict):
            raise ValueError("current_data must be dictionary")
        if not isinstance(update_data, dict):
            raise ValueError("update_data must be dictionary")

        for key, value in update_data.items():
            if not isinstance(key, str):
                raise ValueError("All keys must be strings")

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
                self._deep_update(current_data[key], value)
            else:
                current_data[key] = value

    async def get_shared_data(self, query_id: str) -> Optional[SharedData]:
        """Get shared data using Redis JSON.

        Args:
            query_id: Unique identifier for the query

        Returns:
            SharedData instance if exists, None otherwise

        Raises:
            Exception: For Redis or validation errors
        """
        if not query_id or not isinstance(query_id, str):
            raise ValueError("query_id must be non-empty string")

        key = RedisKeys.get_shared_data_key(query_id)

        try:
            data = await self.redis.json().get(key)
            if data:
                return SharedData(**data)
            return None
        except redis.RedisError as e:
            logger.error(f"Redis error getting shared data for {query_id}: {e}")
            raise
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid shared data format for {query_id}: {e}")
            raise

    async def get_shared_data_field(self, query_id: str, json_path: str) -> Any:
        """Get specific field from shared data using JSONPath.

        Args:
            query_id: Unique identifier for the query
            json_path: JSONPath expression (e.g., '$.agents_done', '$.results.inventory_agent')

        Returns:
            Field value or None if not found

        Examples:
            # Get agents completed
            agents_done = await agent.get_shared_data_field(query_id, '$.agents_done')

            # Get specific agent results
            inventory_results = await agent.get_shared_data_field(query_id, '$.results.InventoryAgent')

            # Get query status
            status = await agent.get_shared_data_field(query_id, '$.status')

        Raises:
            Exception: For Redis or path errors
        """
        if not query_id or not isinstance(query_id, str):
            raise ValueError("query_id must be non-empty string")
        if not json_path or not isinstance(json_path, str):
            raise ValueError("json_path must be non-empty string")

        key = RedisKeys.get_shared_data_key(query_id)

        try:
            return await self.redis.json().get(key, Path(json_path))
        except redis.RedisError as e:
            logger.error(f"Redis error getting field {json_path} for {query_id}: {e}")
            raise

    async def update_shared_data_field(self, query_id: str, json_path: str, value: Any):
        """Update specific field in shared data using JSONPath.

        Args:
            query_id: Unique identifier for the query
            json_path: JSONPath expression (e.g., '$.status', '$.agents_done')
            value: New value to set

        Examples:
            # Update status
            await agent.update_shared_data_field(query_id, '$.status', 'completed')

            # Update specific result
            await agent.update_shared_data_field(query_id, '$.results.InventoryAgent', result_data)

        Raises:
            Exception: For Redis or path errors
        """
        if not query_id or not isinstance(query_id, str):
            raise ValueError("query_id must be non-empty string")
        if not json_path or not isinstance(json_path, str):
            raise ValueError("json_path must be non-empty string")

        key = RedisKeys.get_shared_data_key(query_id)

        try:
            await self.redis.json().set(key, Path(json_path), value)
            logger.debug(f"Updated field {json_path} for {query_id}: {value}")
        except redis.RedisError as e:
            logger.error(f"Redis error updating field {json_path} for {query_id}: {e}")
            raise

    @abstractmethod
    async def start(self):
        """Start the agent. Must be implemented by subclasses."""
        pass
