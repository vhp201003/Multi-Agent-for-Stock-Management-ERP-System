import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts.summary_agent import SUMMARY_AGENT_PROMPTS

from src.agents.base_agent import BaseAgent
from src.typing.llm_response import SummaryResponse
from src.typing.redis import ConversationData, RedisChannels, RedisKeys
from src.typing.schema import SummaryAgentSchema

logger = logging.getLogger(__name__)

AGENT_TYPE = "summary_agent"


class SummaryAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)
        self.prompts = SUMMARY_AGENT_PROMPTS

    async def get_pub_channels(self) -> List[str]:
        return [RedisChannels.TASK_UPDATES]

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def process(self, request: Dict[str, Any]) -> SummaryResponse:
        try:
            conversation_id = request.get("conversation_id")
            if not conversation_id:
                raise ValueError("conversation_id is required")

            logger.info(f"Processing conversation summary for: {conversation_id}")

            conversation = await self._load_conversation(conversation_id)
            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            recent_messages = conversation.get_recent_messages(limit=10)

            if not recent_messages:
                logger.warning(
                    f"No messages to summarize for conversation {conversation_id}"
                )
                return SummaryResponse(
                    conversation_id=conversation_id,
                    summary="No conversation history available",
                    message_count=0,
                    timestamp=datetime.now().isoformat(),
                )

            messages_text = "\n".join(
                [f"{msg['role'].upper()}: {msg['content']}" for msg in recent_messages]
            )

            user_prompt = self.prompts["user_template"].format(
                messages_text=messages_text
            )

            messages = [
                {"role": "system", "content": self.prompts["system"]},
                {"role": "user", "content": user_prompt},
            ]

            summary_response = await self._call_llm(
                messages=messages,
                response_schema=SummaryAgentSchema,
                response_model=SummaryResponse,
            )

            summary_text = ""
            if hasattr(summary_response, "summary"):
                summary_text = summary_response.summary
            elif isinstance(summary_response, str):
                summary_text = summary_response
            else:
                summary_text = str(summary_response)

            await self._update_conversation_summary(conversation_id, summary_text)

            logger.info(f"Successfully summarized conversation {conversation_id}")

            return SummaryResponse(
                conversation_id=conversation_id,
                summary=summary_text,
                message_count=len(recent_messages),
                timestamp=datetime.now().isoformat(),
            )

        except Exception as e:
            logger.error(f"Summary processing failed: {e}")
            return SummaryResponse(
                conversation_id=request.get("conversation_id", "unknown"),
                summary="",
                message_count=0,
                timestamp=datetime.now().isoformat(),
                error=str(e),
            )

    async def _load_conversation(
        self, conversation_id: str
    ) -> Optional[ConversationData]:
        try:
            conversation_key = RedisKeys.get_conversation_key(conversation_id)
            logger.info(
                f"SummaryAgent: Looking for conversation with key: {conversation_key}"
            )

            conversation_data = await self.redis.json().get(conversation_key)

            if conversation_data:
                logger.info(
                    f"SummaryAgent: Found conversation {conversation_id} with {len(conversation_data.get('messages', []))} messages"
                )
                return ConversationData(**conversation_data)
            else:
                logger.warning(
                    f"SummaryAgent: Conversation {conversation_id} not found in Redis"
                )
                all_keys = await self.redis.keys("conversation:*")
                logger.info(f"SummaryAgent: Existing conversation keys: {all_keys}")
                return None

        except Exception as e:
            logger.error(
                f"SummaryAgent: Failed to load conversation {conversation_id}: {e}"
            )
            return None

    async def _update_conversation_summary(
        self, conversation_id: str, summary: str
    ) -> None:
        try:
            conversation_key = RedisKeys.get_conversation_key(conversation_id)

            conversation_data = await self.redis.json().get(conversation_key)
            if not conversation_data:
                logger.error(
                    f"Cannot update summary - conversation {conversation_id} not found"
                )
                return

            conversation = ConversationData(**conversation_data)

            conversation.update_summary(summary)

            # Save back to Redis
            await self.redis.json().set(
                conversation_key,
                "$",
                json.loads(json.dumps(conversation.model_dump())),
            )

            logger.info(f"Updated summary for conversation {conversation_id}")

        except Exception as e:
            logger.error(
                f"Failed to update conversation summary for {conversation_id}: {e}"
            )

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in await self.get_pub_channels():
            raise ValueError(f"SummaryAgent cannot publish to {channel}")

        try:
            await self.redis.publish(channel=channel, message=json.dumps(message))
        except Exception as e:
            logger.error(f"Message publish failed for {channel}: {e}")
            raise

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        logger.info(
                            f"SummaryAgent received command: {data.get('command')}"
                        )

                        if data.get("command") == "summarize":
                            result = await self.process(data)

                            task_update = {
                                "agent_type": AGENT_TYPE,
                                "query_id": data.get("query_id", "unknown"),
                                "sub_query": f"Summarize conversation {data.get('conversation_id')}",
                                "status": "done",
                                "results": result.model_dump(),
                                "context": {},
                                "llm_usage": {},
                                "timestamp": datetime.now().isoformat(),
                            }

                            await self.redis.publish(
                                RedisChannels.TASK_UPDATES, json.dumps(task_update)
                            )

                            logger.info(
                                f"SummaryAgent completed task for conversation {data.get('conversation_id')}"
                            )

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in summary command: {e}")
                    except Exception as e:
                        logger.error(f"SummaryAgent processing error: {e}")

        except Exception as e:
            logger.error(f"Redis error in SummaryAgent listen_channels: {e}")
        finally:
            await pubsub.unsubscribe(*channels)

    async def start(self):
        logger.info("SummaryAgent: Starting conversation summarization service")
        await self.listen_channels()
