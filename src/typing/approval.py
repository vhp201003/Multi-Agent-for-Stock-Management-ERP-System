import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalAction(str, Enum):
    APPROVE = "approve"  # Execute with original params
    MODIFY = "modify"  # Execute with modified params
    REJECT = "reject"  # Cancel execution


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ApprovalRequest(BaseModel):
    # Identifiers
    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query_id: str
    task_id: Optional[str] = None
    agent_type: str

    # Tool information
    tool_name: str
    proposed_params: Dict[str, Any]

    # UI configuration
    title: str = "Action Approval Required"
    description: Optional[str] = None
    modifiable_fields: List[str] = Field(default_factory=list)

    # Timeout
    timeout_seconds: int = 300  # 5 minutes default
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def is_field_modifiable(self, field_name: str) -> bool:
        """Check if a field can be modified by user"""
        return field_name in self.modifiable_fields


class ApprovalResponse(BaseModel):
    approval_id: str
    query_id: str
    action: ApprovalAction
    modified_params: Optional[Dict[str, Any]] = None  # Only for MODIFY action
    reason: Optional[str] = None  # Only for REJECT action
    responded_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_final_params(self, original_params: Dict[str, Any]) -> Dict[str, Any]:
        if self.action == ApprovalAction.MODIFY and self.modified_params:
            # Merge: modified_params overrides original
            return {**original_params, **self.modified_params}
        return original_params
