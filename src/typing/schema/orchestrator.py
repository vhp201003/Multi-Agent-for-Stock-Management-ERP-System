from typing import Dict, List

from pydantic import BaseModel, Field

from .base_schema import BaseSchema


class TaskNode(BaseModel):
    task_id: str = Field(
        ...,
        description="Unique task identifier in format '{agent_type}_{sequence}'",
        pattern=r"^[a-z_]+_\d+$",
        examples=["inventory_1", "ordering_1", "finance_2"],
    )
    agent_type: str = Field(
        ...,
        description="Agent type responsible for this task",
        pattern=r"^[a-z_]+$",
        examples=["inventory", "ordering", "finance"],
    )
    sub_query: str = Field(
        ...,
        description="Specific task for the agent to execute",
        min_length=10,
        max_length=500,
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of task_ids that must complete before this task starts",
    )


class OrchestratorSchema(BaseSchema):
    agents_needed: List[str] = Field(
        ...,
        description="List of agent types required to complete the request",
    )
    task_dependency: Dict[str, List[TaskNode]] = Field(
        default_factory=dict,
        description="Direct mapping: agent_type -> list of tasks",
    )
