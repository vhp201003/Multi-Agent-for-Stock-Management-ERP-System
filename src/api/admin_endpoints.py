import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config.settings import get_redis_host, get_redis_port

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def get_redis():
    client = redis.Redis(
        host=get_redis_host(), port=get_redis_port(), decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


# --- Additional Response Models for Enhanced Dashboard ---


class AgentStatusInfo(BaseModel):
    agent_type: str
    status: str
    queue_size: int = 0
    pending_queue_size: int = 0


class SystemOverview(BaseModel):
    agents: List[AgentStatusInfo]
    pending_approvals: int = 0
    active_queries: int = 0
    total_queued_tasks: int = 0


class LLMUsageStats(BaseModel):
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_requests: int = 0
    avg_response_time_ms: float = 0
    usage_by_agent: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class TaskPerformance(BaseModel):
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    pending_tasks: int = 0
    success_rate: float = 0
    tasks_by_agent: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    recent_errors: List[Dict[str, Any]] = Field(default_factory=list)


class ApprovalStats(BaseModel):
    total_approvals: int = 0
    approved: int = 0
    modified: int = 0
    rejected: int = 0
    pending: int = 0
    avg_response_time_seconds: float = 0
    by_agent: Dict[str, Dict[str, int]] = Field(default_factory=dict)


class TimeSeriesPoint(BaseModel):
    timestamp: str
    value: float


class PerformanceTimeline(BaseModel):
    tokens_over_time: List[TimeSeriesPoint] = Field(default_factory=list)
    tasks_over_time: List[TimeSeriesPoint] = Field(default_factory=list)
    response_times: List[TimeSeriesPoint] = Field(default_factory=list)


# --- Response Models ---


class AdminStatsResponse(BaseModel):
    total_users: int
    active_conversations: int
    message_volume: int
    resolution_rate: float
    stats_change: Dict[str, str]  # e.g., {"total_users": "+1.5%", ...}


class EngagementDataPoint(BaseModel):
    name: str  # e.g., "Week 1" or "2023-10-27"
    value: int


class IntentDataPoint(BaseModel):
    name: str
    value: int


# --- Endpoints ---


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(redis_client: redis.Redis = Depends(get_redis)):
    """Get high-level statistics for the admin dashboard."""
    try:
        # 1. Count Users
        user_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="users:*", count=100
            )
            user_keys.extend(keys)
            if cursor == 0:
                break
        total_users = len(user_keys)

        # 2. Count Conversations & Messages
        conversation_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="conversation:*", count=100
            )
            conversation_keys.extend(keys)
            if cursor == 0:
                break

        active_conversations = len(conversation_keys)
        message_volume = 0

        # We need to read conversation data to count messages
        # To avoid performance hit on large datasets, we could sample or cache this.
        # For now, we'll read all since it's likely small scale.
        for key in conversation_keys:
            try:
                data = await redis_client.json().get(key)
                if data and "messages" in data:
                    message_volume += len(data["messages"])
            except Exception:
                continue

        return AdminStatsResponse(
            total_users=total_users,
            active_conversations=active_conversations,
            message_volume=message_volume,
            resolution_rate=88.0,  # Mocked for now
            stats_change={
                "total_users": "+1.5%",
                "active_conversations": "+8.2%",
                "message_volume": "-0.5%",
                "resolution_rate": "+2.1%",
            },
        )
    except Exception as e:
        logger.error(f"Failed to get admin stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/engagement", response_model=List[EngagementDataPoint])
async def get_engagement_data(redis_client: redis.Redis = Depends(get_redis)):
    """Get user engagement data (messages over time)."""
    try:
        # Initialize last 30 days with 0
        engagement_map = {}
        today = datetime.now()
        for i in range(30):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            engagement_map[date_str] = 0

        # Scan conversations and aggregate messages by date
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="conversation:*", count=100
            )
            for key in keys:
                try:
                    data = await redis_client.json().get(key)
                    if data and "messages" in data:
                        for msg in data["messages"]:
                            # Assuming msg has 'timestamp'
                            ts_str = msg.get("timestamp")
                            if ts_str:
                                try:
                                    # Handle ISO format or other formats
                                    dt = datetime.fromisoformat(
                                        ts_str.replace("Z", "+00:00")
                                    )
                                    date_key = dt.strftime("%Y-%m-%d")
                                    if date_key in engagement_map:
                                        engagement_map[date_key] += 1
                                except ValueError:
                                    continue
                except Exception:
                    continue

            if cursor == 0:
                break

        # Convert to list and sort
        result = [
            EngagementDataPoint(name=date, value=count)
            for date, count in sorted(engagement_map.items())
        ]

        # Simplify for the chart (maybe group by week if too many points, but 30 days is fine)
        return result

    except Exception as e:
        logger.error(f"Failed to get engagement data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intents", response_model=List[IntentDataPoint])
async def get_intent_data(redis_client: redis.Redis = Depends(get_redis)):
    """Get common user intents based on agents_needed in shared_data."""
    try:
        intent_counts: Dict[str, int] = {}
        cursor = 0

        # Scan for all shared_data keys
        # Assuming shared_data keys follow a pattern like "shared_data:*"
        # We need to check RedisKeys but based on utils it seems to be "shared_data:{query_id}"
        # Let's assume the prefix is "shared_data:*"
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="agent:shared_data:*", count=100
            )

            for key in keys:
                try:
                    # Get agents_needed from shared_data
                    # We can use json().get with path to fetch just the field we need
                    agents_needed = await redis_client.json().get(
                        key, "$.agents_needed"
                    )

                    # agents_needed is returned as a list of lists because of JSON path, e.g. [['agent1', 'agent2']]
                    if (
                        agents_needed
                        and isinstance(agents_needed, list)
                        and len(agents_needed) > 0
                    ):
                        actual_agents = agents_needed[0]  # The inner list
                        if isinstance(actual_agents, list):
                            for agent in actual_agents:
                                if isinstance(agent, str):
                                    # Normalize agent name if needed (e.g., "sales_agent" -> "Sales")
                                    agent_name = agent.replace("_", " ").title()
                                    intent_counts[agent_name] = (
                                        intent_counts.get(agent_name, 0) + 1
                                    )
                except Exception:
                    continue

            if cursor == 0:
                break

        # If no data found, return empty list or keep mock for demo if preferred?
        # User asked for real data, so let's return real data.
        if not intent_counts:
            # Fallback to empty or maybe a "No Data" point?
            return []

        # Convert to list and sort by value descending
        result = [
            IntentDataPoint(name=name, value=count)
            for name, count in sorted(
                intent_counts.items(), key=lambda item: item[1], reverse=True
            )
        ]

        # Limit to top 5-10 to avoid cluttering the chart
        return result[:10]

    except Exception as e:
        logger.error(f"Failed to get intent data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- New Enhanced Endpoints ---

KNOWN_AGENTS = [
    "orchestrator",
    "inventory_agent",
    "analytics_agent",
    "forecasting_agent",
    "ordering_agent",
    "summary_agent",
    "chat_agent",
]


@router.get("/system-overview", response_model=SystemOverview)
async def get_system_overview(redis_client: redis.Redis = Depends(get_redis)):
    """Get real-time system overview including agent statuses and queue sizes."""
    try:
        agents = []

        # Get agent statuses from hash
        agent_statuses = await redis_client.hgetall("agent:status")

        for agent_type in KNOWN_AGENTS:
            status = agent_statuses.get(agent_type, "offline")

            # Get queue sizes
            queue_key = f"agent:queue:{agent_type}"
            pending_key = f"agent:pending_queue:{agent_type}"

            queue_size = await redis_client.llen(queue_key)
            pending_size = await redis_client.llen(pending_key)

            agents.append(
                AgentStatusInfo(
                    agent_type=agent_type,
                    status=status,
                    queue_size=queue_size,
                    pending_queue_size=pending_size,
                )
            )

        # Count pending approvals (scan for approval keys with pending status)
        pending_approvals = 0
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="approval:*", count=100
            )
            for key in keys:
                try:
                    data = await redis_client.json().get(key)
                    if data and data.get("status") == "pending":
                        pending_approvals += 1
                except Exception:
                    continue
            if cursor == 0:
                break

        # Count active shared_data (queries in progress)
        active_queries = 0
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="agent:shared_data:*", count=100
            )
            for key in keys:
                try:
                    status = await redis_client.json().get(key, "$.status")
                    if status and status[0] in ["pending", "processing"]:
                        active_queries += 1
                except Exception:
                    continue
            if cursor == 0:
                break

        total_queued = sum(a.queue_size + a.pending_queue_size for a in agents)

        return SystemOverview(
            agents=agents,
            pending_approvals=pending_approvals,
            active_queries=active_queries,
            total_queued_tasks=total_queued,
        )

    except Exception as e:
        logger.error(f"Failed to get system overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm-usage", response_model=LLMUsageStats)
async def get_llm_usage_stats(redis_client: redis.Redis = Depends(get_redis)):
    """Get LLM token usage and performance statistics from shared_data."""
    try:
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_requests = 0
        total_time_ms = 0.0
        usage_by_agent: Dict[str, Dict[str, Any]] = {}

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="agent:shared_data:*", count=100
            )

            for key in keys:
                try:
                    llm_usage = await redis_client.json().get(key, "$.llm_usage")
                    if llm_usage and isinstance(llm_usage, list) and llm_usage[0]:
                        usage_data = llm_usage[0]  # Dict of agent_type -> usage
                        for agent_type, usage in usage_data.items():
                            if not isinstance(usage, dict):
                                continue

                            prompt = usage.get("prompt_tokens") or 0
                            completion = usage.get("completion_tokens") or 0
                            total = usage.get("total_tokens") or (prompt + completion)
                            response_time = (
                                usage.get("total_time") or 0
                            ) * 1000  # to ms

                            total_tokens += total
                            total_prompt_tokens += prompt
                            total_completion_tokens += completion
                            total_requests += 1
                            total_time_ms += response_time

                            # Aggregate by agent
                            if agent_type not in usage_by_agent:
                                usage_by_agent[agent_type] = {
                                    "total_tokens": 0,
                                    "prompt_tokens": 0,
                                    "completion_tokens": 0,
                                    "requests": 0,
                                    "avg_response_time_ms": 0,
                                    "total_time_ms": 0,
                                }
                            usage_by_agent[agent_type]["total_tokens"] += total
                            usage_by_agent[agent_type]["prompt_tokens"] += prompt
                            usage_by_agent[agent_type]["completion_tokens"] += (
                                completion
                            )
                            usage_by_agent[agent_type]["requests"] += 1
                            usage_by_agent[agent_type]["total_time_ms"] += response_time
                except Exception:
                    continue

            if cursor == 0:
                break

        # Calculate averages
        avg_response_time = total_time_ms / total_requests if total_requests > 0 else 0

        for agent_type, data in usage_by_agent.items():
            if data["requests"] > 0:
                data["avg_response_time_ms"] = round(
                    data["total_time_ms"] / data["requests"], 2
                )
            del data["total_time_ms"]  # Remove temp field

        return LLMUsageStats(
            total_tokens=total_tokens,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_requests=total_requests,
            avg_response_time_ms=round(avg_response_time, 2),
            usage_by_agent=usage_by_agent,
        )

    except Exception as e:
        logger.error(f"Failed to get LLM usage stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task-performance", response_model=TaskPerformance)
async def get_task_performance(redis_client: redis.Redis = Depends(get_redis)):
    """Get task execution performance metrics from shared_data."""
    try:
        total_tasks = 0
        completed_tasks = 0
        failed_tasks = 0
        pending_tasks = 0
        tasks_by_agent: Dict[str, Dict[str, int]] = {}
        recent_errors: List[Dict[str, Any]] = []

        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="agent:shared_data:*", count=100
            )

            for key in keys:
                try:
                    tasks_data = await redis_client.json().get(key, "$.tasks")
                    query_id = key.split(":")[-1]

                    if tasks_data and isinstance(tasks_data, list) and tasks_data[0]:
                        tasks = tasks_data[0]  # Dict of task_id -> task execution
                        for task_id, execution in tasks.items():
                            if not isinstance(execution, dict):
                                continue

                            total_tasks += 1
                            status = execution.get("status", "pending")
                            task_info = execution.get("task", {})
                            agent_type = task_info.get("agent_type", "unknown")

                            # Initialize agent stats
                            if agent_type not in tasks_by_agent:
                                tasks_by_agent[agent_type] = {
                                    "completed": 0,
                                    "failed": 0,
                                    "pending": 0,
                                }

                            if status == "completed":
                                completed_tasks += 1
                                tasks_by_agent[agent_type]["completed"] += 1
                            elif status == "failed":
                                failed_tasks += 1
                                tasks_by_agent[agent_type]["failed"] += 1
                                # Collect recent errors
                                if len(recent_errors) < 10:
                                    recent_errors.append(
                                        {
                                            "query_id": query_id,
                                            "task_id": task_id,
                                            "agent_type": agent_type,
                                            "error": execution.get("error", "Unknown"),
                                            "sub_query": task_info.get("sub_query", ""),
                                        }
                                    )
                            else:
                                pending_tasks += 1
                                tasks_by_agent[agent_type]["pending"] += 1
                except Exception:
                    continue

            if cursor == 0:
                break

        success_rate = (
            round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0
        )

        return TaskPerformance(
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            pending_tasks=pending_tasks,
            success_rate=success_rate,
            tasks_by_agent=tasks_by_agent,
            recent_errors=recent_errors,
        )

    except Exception as e:
        logger.error(f"Failed to get task performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approval-stats", response_model=ApprovalStats)
async def get_approval_stats(redis_client: redis.Redis = Depends(get_redis)):
    """Get HITL approval workflow statistics."""
    try:
        total = 0
        approved = 0
        modified = 0
        rejected = 0
        pending = 0
        total_response_time = 0.0
        responded_count = 0
        by_agent: Dict[str, Dict[str, int]] = {}

        # Scan approval keys
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="approval:*", count=100
            )

            for key in keys:
                try:
                    data = await redis_client.json().get(key)
                    if not data:
                        continue

                    total += 1
                    status = data.get("status", "pending")
                    agent_type = data.get("agent_type", "unknown")

                    # Initialize agent stats
                    if agent_type not in by_agent:
                        by_agent[agent_type] = {
                            "approved": 0,
                            "modified": 0,
                            "rejected": 0,
                            "pending": 0,
                        }

                    if status == "approved":
                        approved += 1
                        by_agent[agent_type]["approved"] += 1
                    elif status == "modified":
                        modified += 1
                        by_agent[agent_type]["modified"] += 1
                    elif status == "rejected":
                        rejected += 1
                        by_agent[agent_type]["rejected"] += 1
                    else:
                        pending += 1
                        by_agent[agent_type]["pending"] += 1

                    # Calculate response time if responded
                    created_at = data.get("created_at")
                    responded_at = data.get("responded_at")
                    if created_at and responded_at:
                        try:
                            created = datetime.fromisoformat(created_at)
                            responded = datetime.fromisoformat(responded_at)
                            total_response_time += (responded - created).total_seconds()
                            responded_count += 1
                        except ValueError:
                            pass
                except Exception:
                    continue

            if cursor == 0:
                break

        avg_response_time = (
            round(total_response_time / responded_count, 1)
            if responded_count > 0
            else 0
        )

        return ApprovalStats(
            total_approvals=total,
            approved=approved,
            modified=modified,
            rejected=rejected,
            pending=pending,
            avg_response_time_seconds=avg_response_time,
            by_agent=by_agent,
        )

    except Exception as e:
        logger.error(f"Failed to get approval stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent-workload")
async def get_agent_workload(redis_client: redis.Redis = Depends(get_redis)):
    """Get detailed workload distribution per agent."""
    try:
        workload: Dict[str, Dict[str, Any]] = {}

        for agent_type in KNOWN_AGENTS:
            queue_size = await redis_client.llen(f"agent:queue:{agent_type}")
            pending_size = await redis_client.llen(f"agent:pending_queue:{agent_type}")
            status = await redis_client.hget("agent:status", agent_type) or "offline"

            workload[agent_type] = {
                "status": status,
                "active_tasks": queue_size,
                "pending_tasks": pending_size,
                "total_load": queue_size + pending_size,
            }

        # Get historical task counts from shared_data
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor, match="agent:shared_data:*", count=100
            )

            for key in keys:
                try:
                    agents = await redis_client.json().get(key, "$.agents_needed")
                    if agents and agents[0]:
                        for agent in agents[0]:
                            if agent in workload:
                                workload[agent]["historical_tasks"] = (
                                    workload[agent].get("historical_tasks", 0) + 1
                                )
                except Exception:
                    continue

            if cursor == 0:
                break

        return workload

    except Exception as e:
        logger.error(f"Failed to get agent workload: {e}")
        raise HTTPException(status_code=500, detail=str(e))
