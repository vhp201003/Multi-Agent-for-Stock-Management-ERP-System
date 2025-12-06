from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.typing.redis.constants import TaskStatus
from src.typing.schema.orchestrator import TaskNode


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
    result_references: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

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

    def store_result_reference(
        self, result_id: str, tool_name: str, tool_result: dict, agent_type: str
    ) -> None:
        """Store mapping from result_id → full tool result for tracing"""
        self.result_references[result_id] = {
            "tool_name": tool_name,
            "data": tool_result,
            "agent_type": agent_type,
        }

    def get_result_by_id(self, result_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full tool result by its ID"""
        return self.result_references.get(result_id)

    def get_dependency_results(self, task_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get results from completed dependency tasks for a given task_id.

        Args:
            task_id: The task_id to get dependency results for

        Returns:
            List of dependency results with task info, or None if no dependencies
        """
        if not task_id or task_id not in self.tasks:
            return None

        current_task = self.tasks[task_id]
        if not current_task.task.dependencies:
            return None

        dep_results = []
        for dep_id in current_task.task.dependencies:
            dep_task = self.tasks.get(dep_id)
            dep_results.append(
                {
                    "task_id": dep_id,
                    "agent_type": dep_task.task.agent_type,
                    "sub_query": dep_task.task.sub_query,
                    "result": dep_task.result,
                }
            )

        return dep_results if dep_results else None
