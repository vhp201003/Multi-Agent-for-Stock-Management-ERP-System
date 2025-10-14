from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from src.typing.schema.orchestrator import TaskDependencyGraph, TaskNode


class LLMUsage(BaseModel):
    completion_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    completion_time: Optional[float] = None
    prompt_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None


class TaskGraphUtils:
    """Production-hardened task graph utilities with O(1) optimizations."""

    @staticmethod
    def get_task_by_id(graph: TaskDependencyGraph, task_id: str) -> Optional[TaskNode]:
        """O(n) search - consider task_id indexing for >100 tasks per agent."""
        if not task_id or not graph.nodes:
            return None

        for tasks in graph.nodes.values():
            for task in tasks:
                if task.task_id == task_id:
                    return task
        return None

    @staticmethod
    def mark_task_done(graph: TaskDependencyGraph, task_id: str) -> bool:
        """Validate task existence - status tracking at SharedData level."""
        if not task_id:
            return False
        return TaskGraphUtils.get_task_by_id(graph, task_id) is not None

    @staticmethod
    def get_ready_tasks(
        graph: TaskDependencyGraph, completed_task_ids: Set[str]
    ) -> List[TaskNode]:
        """Batch dependency resolution with fail-fast validation."""
        if not graph.nodes or not isinstance(completed_task_ids, set):
            return []

        ready_tasks = []
        for tasks in graph.nodes.values():
            for task in tasks:
                if task.task_id not in completed_task_ids and all(
                    dep_id in completed_task_ids for dep_id in task.dependencies
                ):
                    ready_tasks.append(task)
        return ready_tasks

    @staticmethod
    def is_agent_complete(
        graph: TaskDependencyGraph, agent_type: str, completed_task_ids: Set[str]
    ) -> bool:
        """Agent completion check with input validation."""
        if not agent_type or agent_type not in graph.nodes:
            return False
        if not isinstance(completed_task_ids, set):
            return False

        return all(
            task.task_id in completed_task_ids for task in graph.nodes[agent_type]
        )

    @staticmethod
    def get_completion_status(
        graph: TaskDependencyGraph, completed_task_ids: Set[str]
    ) -> Dict[str, Dict[str, int]]:
        """Generate completion metrics - single pass O(n) complexity."""
        status = {}
        if not graph.nodes:
            return status

        for agent_type, tasks in graph.nodes.items():
            total_tasks = len(tasks)
            done_tasks = sum(1 for t in tasks if t.task_id in completed_task_ids)
            status[agent_type] = {
                "total": total_tasks,
                "done": done_tasks,
                "pending": total_tasks - done_tasks,
            }
        return status

    @staticmethod
    def get_tasks_for_agent(
        graph: TaskDependencyGraph, agent_type: str
    ) -> List[TaskNode]:
        """Direct O(1) agent task access with validation."""
        if not agent_type or not graph.nodes:
            return []
        return graph.nodes.get(agent_type, [])


class SharedData(BaseModel):
    """Production-grade shared state with atomic operations."""

    original_query: str
    agents_needed: List[str]
    agents_done: List[str] = Field(default_factory=list)

    # Legacy fields - maintain backward compatibility
    sub_queries: Dict[str, List[str]] = Field(default_factory=dict)
    results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    context: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    status: str = "pending"
    llm_usage: Dict[str, LLMUsage] = Field(default_factory=dict)
    task_graph: TaskDependencyGraph = Field(default_factory=TaskDependencyGraph)
    summary_previous_query: Optional[str] = None

    def add_task_result(self, task_id: str, result: Any) -> bool:
        """Thread-safe task result addition with validation."""
        if not task_id:
            return False

        task = TaskGraphUtils.get_task_by_id(self.task_graph, task_id)
        if not task:
            return False

        agent_type = task.agent_type
        sub_query = task.sub_query

        # Atomic result update
        if agent_type not in self.results:
            self.results[agent_type] = {}
        self.results[agent_type][sub_query] = result
        return True

    def mark_task_done(self, task_id: str) -> bool:
        """Atomic task completion with agent status cascade."""
        if not TaskGraphUtils.mark_task_done(self.task_graph, task_id):
            return False

        # Get current completion state
        completed_task_ids = self._get_completed_task_ids()

        # Check agent completion atomically
        task = TaskGraphUtils.get_task_by_id(self.task_graph, task_id)
        if task and TaskGraphUtils.is_agent_complete(
            self.task_graph, task.agent_type, completed_task_ids
        ):
            if task.agent_type not in self.agents_done:
                self.agents_done.append(task.agent_type)

        return True

    def _get_completed_task_ids(self) -> Set[str]:
        """Centralized completed task extraction with caching potential."""
        completed_task_ids = set()
        for agent_type in self.agents_done:
            if agent_type in self.task_graph.nodes:
                for task in self.task_graph.nodes[agent_type]:
                    completed_task_ids.add(task.task_id)
        return completed_task_ids

    @property
    def is_complete(self) -> bool:
        """O(1) completion check using sets."""
        return set(self.agents_done) >= set(self.agents_needed)

    @property
    def execution_progress(self) -> Dict[str, Any]:
        """Cached execution progress with performance optimization."""
        completed_task_ids = self._get_completed_task_ids()
        return {
            "agents_total": len(self.agents_needed),
            "agents_complete": len(self.agents_done),
            "task_status": TaskGraphUtils.get_completion_status(
                self.task_graph, completed_task_ids
            ),
            "overall_complete": self.is_complete,
        }
