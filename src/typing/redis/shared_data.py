from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.typing.schema.orchestrator import TaskNode


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class LLMUsage(BaseModel):
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None


class TaskExecution(BaseModel):
    task: TaskNode
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None


class SharedData(BaseModel):
    original_query: str
    query_id: str
    agents_needed: List[str]
    tasks: Dict[str, TaskExecution] = Field(
        default_factory=dict
    )  # task_id -> TaskExecution
    status: str = "pending"
    llm_usage: Dict[str, LLMUsage] = Field(default_factory=dict)
    conversation_id: Optional[str] = None

    def add_task(self, task: TaskNode) -> bool:
        if not task.task_id or task.task_id in self.tasks:
            return False

        self.tasks[task.task_id] = TaskExecution(task=task)
        return True

    def get_ready_tasks(self) -> List[TaskNode]:
        ready = []

        for execution in self.tasks.values():
            if execution.status != TaskStatus.PENDING:
                continue

            dependencies_met = True
            for dep_id in execution.task.dependencies:
                if (
                    dep_id not in self.tasks
                    or self.tasks[dep_id].status != TaskStatus.COMPLETED
                ):
                    dependencies_met = False
                    break

            if dependencies_met:
                ready.append(execution.task)

        return ready

    def complete_task(self, task_id: str, result: Any) -> bool:
        if not task_id or task_id not in self.tasks:
            return False

        self.tasks[task_id].status = TaskStatus.COMPLETED
        self.tasks[task_id].result = result
        return True

    def fail_task(self, task_id: str, error: str) -> bool:
        if not task_id or task_id not in self.tasks:
            return False

        self.tasks[task_id].status = TaskStatus.FAILED
        self.tasks[task_id].error = error or "Unknown error"
        return True

    def get_agent_results(self, agent_type: str) -> Dict[str, Any]:
        if not agent_type:
            return {}

        results = {}
        for execution in self.tasks.values():
            if (
                execution.task.agent_type == agent_type
                and execution.status == TaskStatus.COMPLETED
                and execution.result is not None
            ):
                results[execution.task.task_id] = execution.result

        return results

    def get_tasks_for_agent(self, agent_type: str) -> List[TaskNode]:
        if not agent_type:
            return []

        return [
            execution.task
            for execution in self.tasks.values()
            if execution.task.agent_type == agent_type
        ]

    def get_task_id_by_sub_query(
        self, agent_type: str, sub_query: str
    ) -> Optional[str]:
        for execution in self.tasks.values():
            if (
                execution.task.agent_type == agent_type
                and execution.task.sub_query == sub_query
            ):
                return execution.task.task_id
        return None

    @property
    def is_complete(self) -> bool:
        """Check if all tasks completed successfully."""
        return len(self.tasks) > 0 and all(
            execution.status == TaskStatus.COMPLETED
            for execution in self.tasks.values()
        )
