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
    task_status: str = Field(
        "pending",
        description="Current status: 'pending', 'in_progress', 'completed', 'failed'",
    )
    agent_type: str = Field(
        ...,
        description="Agent responsible for executing this task",
        examples=["inventory", "ordering", "finance", "chat"],
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


# Direct agent_type -> tasks mapping
class TaskDependencyGraph(BaseModel):
    nodes: Dict[str, List[TaskNode]] = Field(
        default_factory=dict,
        description="Direct mapping: agent_type -> list of tasks",
        examples=[
            {
                "inventory": [
                    {
                        "task_id": "inventory_1",
                        "agent_type": "inventory",
                        "sub_query": "Check stock levels",
                        "dependencies": [],
                    }
                ],
                "ordering": [
                    {
                        "task_id": "ordering_1",
                        "agent_type": "ordering",
                        "sub_query": "Create purchase order",
                        "dependencies": ["inventory_1"],
                    }
                ],
            }
        ],
    )


class OrchestratorSchema(BaseSchema):
    agents_needed: List[str] = Field(
        ...,
        description="List of agent types required to complete the request",
    )
    task_dependency: TaskDependencyGraph = Field(
        default_factory=TaskDependencyGraph,
        description="Task dependency graph with direct agent->tasks mapping",
    )
