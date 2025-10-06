from typing import Dict, List

from pydantic import BaseModel, Field

from .base_schema import BaseSchema


class TaskNode(BaseModel):
    task_id: str = Field(
        ..., 
        description="Unique task identifier in format '{agent_type}_{sequence}' (e.g., 'inventory_1', 'ordering_2'). Must be sequential within each agent.",
        pattern=r"^[a-z_]+_\d+$",
        examples=["inventory_1", "ordering_1", "finance_2"]
    )
    agent_type: str = Field(
        ...,
        description="Agent responsible for executing this task. Must match one of the agents in agents_needed.",
        examples=["inventory", "ordering", "finance", "chat"]
    )
    sub_query: str = Field(
        ...,
        description="Specific task or question for the agent to execute. Be precise and actionable.",
        min_length=10,
        max_length=500,
        examples=["Check current stock levels for product ABC-123", "Generate purchase order for low stock items"]
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="List of task_ids that must complete before this task can start. Use exact task_id format. Empty list means no dependencies.",
        examples=[["inventory_1"], ["inventory_1", "ordering_1"], []]
    )


class AgentNode(BaseModel):
    tasks: List[TaskNode] = Field(
        default_factory=list,
        description="List of tasks assigned to this agent. Tasks will be executed based on their dependencies.",
        min_items=1,
        max_items=10
    )


class TaskDependencyGraph(BaseModel):
    nodes: Dict[str, AgentNode] = Field(
        default_factory=dict,
        description="Mapping of agent_type to their assigned tasks. Keys must match agents_needed list.",
        examples=[{
            "inventory": {"tasks": [{"task_id": "inventory_1", "agent_type": "inventory", "sub_query": "Check stock", "dependencies": []}]},
            "ordering": {"tasks": [{"task_id": "ordering_1", "agent_type": "ordering", "sub_query": "Create order", "dependencies": ["inventory_1"]}]}
        }]
    )


class OrchestratorSchema(BaseSchema):
    agents_needed: List[str] = Field(
        ...,
        description="List of agent types required to complete the user's request. Must match task_dependency node keys.",
        examples=[["inventory", "ordering"], ["finance", "chat"], ["inventory", "ordering", "finance"]]
    )
    task_dependency: TaskDependencyGraph = Field(
        default_factory=TaskDependencyGraph,
        description="Task dependency graph defining execution order. Each agent must have at least one task."
    )