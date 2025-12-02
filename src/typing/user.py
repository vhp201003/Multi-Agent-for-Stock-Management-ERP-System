from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class HITLMode(str, Enum):
    """Human-in-the-loop mode for tool approvals."""
    REVIEW = "review"        # User must approve each tool call
    AUTO_APPROVE = "auto"    # Automatically approve all tool calls


class UserSettings(BaseModel):
    """User preferences and settings."""
    hitl_mode: HITLMode = Field(
        default=HITLMode.REVIEW,
        description="How to handle tool approval requests"
    )


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class User(UserBase):
    id: str
    is_active: bool = True
    settings: UserSettings = Field(default_factory=UserSettings)

    class Config:
        from_attributes = True


class UserSettingsUpdate(BaseModel):
    """Partial update for user settings."""
    hitl_mode: Optional[HITLMode] = None


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None
