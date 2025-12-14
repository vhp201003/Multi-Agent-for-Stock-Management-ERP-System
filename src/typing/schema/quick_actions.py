from pydantic import Field

from .base_schema import BaseSchema


class QuickActionsSchema(BaseSchema):
    suggestions: list[str] = Field(
        ...,
        description="List of contextual quick action suggestions for the next user message",
        min_length=3,
        max_length=5,
    )
