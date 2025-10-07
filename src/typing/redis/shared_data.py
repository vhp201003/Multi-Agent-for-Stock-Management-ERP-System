from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

# Import the schema version to maintain consistency
from src.typing.schema.orchestrator import TaskDependencyGraph, TaskNode


class LLMUsage(BaseModel):
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None


# Runtime utility functions for TaskDependencyGraph
class TaskGraphUtils:
    """Utility class for TaskDependencyGraph runtime operations."""

    @staticmethod
    def get_task_by_id(graph: TaskDependencyGraph, task_id: str) -> Optional[TaskNode]:
        """Find a task by ID across all agent nodes."""
        for agent_node in graph.nodes.values():
            for task in agent_node.tasks:
                if task.task_id == task_id:
                    return task
        return None

    @staticmethod
    def mark_task_done(graph: TaskDependencyGraph, task_id: str) -> bool:
        """Mark a task as done and return success status."""
        # TaskNode schema doesn't have status field - this is handled at SharedData level
        task = TaskGraphUtils.get_task_by_id(graph, task_id)
        return task is not None

    @staticmethod
    def get_ready_tasks(
        graph: TaskDependencyGraph, completed_task_ids: Set[str]
    ) -> List[TaskNode]:
        """Get all tasks that are ready to execute."""
        ready_tasks = []
        for agent_node in graph.nodes.values():
            for task in agent_node.tasks:
                # Check if task dependencies are satisfied and task not completed yet
                if task.task_id not in completed_task_ids and all(
                    dep_id in completed_task_ids for dep_id in task.dependencies
                ):
                    ready_tasks.append(task)
        return ready_tasks

    @staticmethod
    def is_agent_complete(
        graph: TaskDependencyGraph, agent_type: str, completed_task_ids: Set[str]
    ) -> bool:
        """Check if all tasks for an agent are complete."""
        if agent_type not in graph.nodes:
            return False
        agent_node = graph.nodes[agent_type]
        return all(task.task_id in completed_task_ids for task in agent_node.tasks)

    @staticmethod
    def get_completion_status(
        graph: TaskDependencyGraph, completed_task_ids: Set[str]
    ) -> Dict[str, Dict[str, int]]:
        """Get completion statistics for all agents."""
        status = {}
        for agent_type, agent_node in graph.nodes.items():
            total_tasks = len(agent_node.tasks)
            done_tasks = sum(
                1 for t in agent_node.tasks if t.task_id in completed_task_ids
            )
            status[agent_type] = {
                "total": total_tasks,
                "done": done_tasks,
                "pending": total_tasks - done_tasks,
            }
        return status


class SharedData(BaseModel):
    original_query: str
    agents_needed: List[str]
    agents_done: List[str] = Field(default_factory=list)

    sub_queries: Dict[str, List[str]] = Field(
        default_factory=dict
    )  # agent_type -> list of sub_queries

    results: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )  # agent_type -> {sub_query: result}
    context: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )  # agent_type -> {sub_query: context}
    status: str = "pending"
    llm_usage: Dict[str, LLMUsage] = Field(
        default_factory=dict
    )  # agent_type -> LLMUsage

    task_graph: TaskDependencyGraph = Field(default_factory=TaskDependencyGraph)

    summary_previous_query: Optional[str] = None

    def add_task_result(self, task_id: str, result: Any):
        """Add result for a specific task."""
        task = TaskGraphUtils.get_task_by_id(self.task_graph, task_id)
        if task:
            agent_type = task.agent_type
            sub_query = task.sub_query

            if agent_type not in self.results:
                self.results[agent_type] = {}
            self.results[agent_type][sub_query] = result

    def mark_task_done(self, task_id: str) -> bool:
        """Mark a task as done and update agent completion status."""
        success = TaskGraphUtils.mark_task_done(self.task_graph, task_id)
        if not success:
            return False

        # Create completed task IDs set based on agents_done
        completed_task_ids = set()
        for agent_type in self.agents_done:
            if agent_type in self.task_graph.nodes:
                for task in self.task_graph.nodes[agent_type].tasks:
                    completed_task_ids.add(task.task_id)

        # Check if agent is complete
        task = TaskGraphUtils.get_task_by_id(self.task_graph, task_id)
        if task:
            if TaskGraphUtils.is_agent_complete(
                self.task_graph, task.agent_type, completed_task_ids
            ):
                if task.agent_type not in self.agents_done:
                    self.agents_done.append(task.agent_type)

        return True

    @property
    def is_complete(self) -> bool:
        return set(self.agents_done) >= set(self.agents_needed)

    @property
    def execution_progress(self) -> Dict[str, Any]:
        """Get current execution progress summary."""
        # Create completed task IDs set based on agents_done
        completed_task_ids = set()
        for agent_type in self.agents_done:
            if agent_type in self.task_graph.nodes:
                for task in self.task_graph.nodes[agent_type].tasks:
                    completed_task_ids.add(task.task_id)

        return {
            "agents_total": len(self.agents_needed),
            "agents_complete": len(self.agents_done),
            "task_status": TaskGraphUtils.get_completion_status(
                self.task_graph, completed_task_ids
            ),
            "overall_complete": self.is_complete,
        }
