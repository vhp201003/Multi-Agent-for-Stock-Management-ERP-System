from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalLevel(str, Enum):
    """Level of approval required for a tool"""

    NONE = "none"  # Auto execute - no approval needed
    CONFIRM = "confirm"  # Simple Yes/No confirmation
    REVIEW = "review"  # User can review and modify params before execution


class MCPToolOutputSchema(BaseModel):
    """Base output schema for MCP tools"""

    success: bool = True
    error: str | None = None


class HITLMetadata(BaseModel):
    """
    Human-in-the-Loop metadata for MCP tools.

    Attached to tool definition to indicate approval requirements.
    Agent reads this to determine if it should pause and ask user.

    Example:
        HITLMetadata(
            requires_approval=True,
            approval_level=ApprovalLevel.REVIEW,
            modifiable_fields=["quantity", "supplier_id"],
            approval_message="Please review this purchase order"
        )
    """

    requires_approval: bool = False
    approval_level: ApprovalLevel = ApprovalLevel.NONE
    modifiable_fields: List[str] = Field(default_factory=list)
    approval_message: Optional[str] = None
    timeout_seconds: int = 300  # 5 minutes default

    def to_annotations(self) -> Dict[str, Any]:
        """
        Convert to MCP-compatible annotations format.

        These get embedded in the tool schema for clients to read.
        """
        if not self.requires_approval:
            return {}

        return {
            "x-hitl-requires-approval": True,
            "x-hitl-level": self.approval_level.value,
            "x-hitl-modifiable-fields": self.modifiable_fields,
            "x-hitl-message": self.approval_message,
            "x-hitl-timeout": self.timeout_seconds,
        }

    @classmethod
    def from_annotations(cls, annotations: Dict[str, Any]) -> "HITLMetadata":
        """
        Parse HITLMetadata from MCP tool annotations.

        Used by agent to reconstruct HITL config from tool schema.
        """
        if not annotations or not annotations.get("x-hitl-requires-approval"):
            return cls()

        level_str = annotations.get("x-hitl-level", "none")
        try:
            level = ApprovalLevel(level_str)
        except ValueError:
            level = ApprovalLevel.NONE

        return cls(
            requires_approval=True,
            approval_level=level,
            modifiable_fields=annotations.get("x-hitl-modifiable-fields", []),
            approval_message=annotations.get("x-hitl-message"),
            timeout_seconds=annotations.get("x-hitl-timeout", 300),
        )
