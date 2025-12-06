from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

from .base_schema import BaseSchema


class ReasoningStep(BaseModel):
    step: str = Field(
        ...,
        description="Brief label for this reasoning step (e.g., 'Analyze Query', 'Match Agents')",
    )
    explanation: str = Field(
        ...,
        description="Detailed explanation of the reasoning in this step",
    )
    conclusion: str = Field(
        ...,
        description="Brief conclusion or output of this step",
    )


class TaskNode(BaseModel):
    task_id: str = Field(
        ...,
        description="Unique task identifier for this task",
        examples=["inventory_1", "ordering_1", "finance_2"],
    )
    agent_type: str = Field(
        ...,
        description="Agent type responsible for this task",
        examples=["inventory", "ordering", "finance"],
    )
    sub_query: str = Field(
        ...,
        description="Specific task for the agent to execute",
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of task_ids that must complete before this task starts",
    )


class OrchestratorSchema(BaseSchema):
    reasoning_steps: List[ReasoningStep] = Field(
        default_factory=list,
        description="Step-by-step reasoning process before making the final decision",
    )
    agents_needed: List[str] = Field(
        ...,
        description="List of agent types required to complete the request (empty if conversational query)",
    )
    task_dependency: Dict[str, List[TaskNode]] = Field(
        default_factory=dict,
        description="Direct mapping: agent_type -> list of tasks",
    )

    @field_validator("task_dependency", mode="before")
    @classmethod
    def transform_task_dependency(cls, v):
        if isinstance(v, dict):
            if "nodes" in v:
                if isinstance(v["nodes"], list):
                    # Old format: {'nodes': List[TaskNode]}
                    transformed = {}
                    for task in v["nodes"]:
                        if isinstance(task, dict):
                            task_obj = TaskNode(**task)
                            agent_type = task_obj.agent_type
                            if agent_type not in transformed:
                                transformed[agent_type] = []
                            transformed[agent_type].append(task_obj)
                    return transformed
                elif isinstance(v["nodes"], dict):
                    # New old format: {'nodes': {'agent_type': List[TaskNode]}}
                    transformed = {}
                    for agent_type, tasks in v["nodes"].items():
                        if isinstance(tasks, list):
                            transformed[agent_type] = [
                                TaskNode(**task) if isinstance(task, dict) else task
                                for task in tasks
                            ]
                    return transformed
        return v
