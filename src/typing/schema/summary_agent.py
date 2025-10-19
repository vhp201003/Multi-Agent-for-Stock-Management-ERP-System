from pydantic import Field

from .base_schema import BaseSchema


class SummaryAgentSchema(BaseSchema):
    summary: str = Field(
        ...,
        description="Concise summary of the conversation covering key topics, decisions, and action items",
    )
