import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.prompts.summary_agent import SUMMARY_AGENT_PROMPTS
from src.agents.base_agent import BaseAgent
from src.typing.llm_response import SummaryResponse
from src.typing.redis import (
    CommandMessage,
    ConversationData,
    RedisChannels,
    RedisKeys,
)
from src.typing.schema import SummaryAgentSchema

logger = logging.getLogger(__name__)

AGENT_TYPE = "summary_agent"


class SummaryAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(agent_type=AGENT_TYPE, **kwargs)
        self.prompts = SUMMARY_AGENT_PROMPTS

    async def get_sub_channels(self) -> List[str]:
        return [RedisChannels.get_command_channel(self.agent_type)]

    async def process(self, command_message: CommandMessage) -> SummaryResponse:
        try:
            conversation_id = command_message.conversation_id
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
                    query_id=command_message.query_id,
                    conversation_id=conversation_id,
                    result=None,
                    error="No messages to summarize",
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

            result, llm_usage, llm_reasoning = await self._call_llm(
                query_id=command_message.query_id,
                messages=messages,
                response_schema=SummaryAgentSchema,
            )

            summary_response = SummaryResponse(
                query_id=command_message.query_id,
                conversation_id=conversation_id,
                result=result,
                llm_usage=llm_usage,
                llm_reasoning=llm_reasoning,
            )

            return summary_response

        except Exception as e:
            logger.error(f"Summary processing failed: {e}")
            return SummaryResponse(
                conversation_id=command_message.conversation_id,
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
            conversation_data = await self.redis.json().get(conversation_key)

            if conversation_data:
                return ConversationData(**conversation_data)
            else:
                logger.warning(
                    f"SummaryAgent: Conversation {conversation_id} not found in Redis"
                )
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

            await self.redis.json().set(
                conversation_key,
                "$",
                conversation.model_dump(mode="json"),
            )

        except Exception as e:
            logger.error(
                f"Failed to update conversation summary for {conversation_id}: {e}"
            )

    async def publish_channel(self, channel: str, message: Dict[str, Any]):
        pass

    async def listen_channels(self):
        pubsub = self.redis.pubsub()
        channels = await self.get_sub_channels()
        await pubsub.subscribe(*channels)

        try:
            async for message in pubsub.listen():
                if (
                    message["channel"] == RedisChannels.get_command_channel(AGENT_TYPE)
                    and message["type"] == "message"
                ):
                    try:
                        command_message = CommandMessage.model_validate_json(
                            message["data"]
                        )
                        if command_message.command == "summarize":
                            summary_response: SummaryResponse = await self.process(
                                command_message
                            )

                            await self._update_conversation_summary(
                                command_message.conversation_id,
                                summary_response.result.summary,
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
