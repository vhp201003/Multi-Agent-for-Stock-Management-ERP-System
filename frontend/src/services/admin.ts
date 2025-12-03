import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add interceptor to add token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface AdminStats {
  total_users: number;
  active_conversations: number;
  message_volume: number;
  resolution_rate: number;
  stats_change: {
    total_users: string;
    active_conversations: string;
    message_volume: string;
    resolution_rate: string;
  };
}

export interface EngagementDataPoint {
  name: string;
  value: number;
}

export interface IntentDataPoint {
  name: string;
  value: number;
}

// New types for enhanced dashboard
export interface AgentStatusInfo {
  agent_type: string;
  status: string;
  queue_size: number;
  pending_queue_size: number;
}

export interface SystemOverview {
  agents: AgentStatusInfo[];
  pending_approvals: number;
  active_queries: number;
  total_queued_tasks: number;
}

export interface LLMUsageStats {
  total_tokens: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_requests: number;
  avg_response_time_ms: number;
  usage_by_agent: Record<string, {
    total_tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    requests: number;
    avg_response_time_ms: number;
  }>;
}

export interface TaskPerformance {
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  pending_tasks: number;
  success_rate: number;
  tasks_by_agent: Record<string, {
    completed: number;
    failed: number;
    pending: number;
  }>;
  recent_errors: Array<{
    query_id: string;
    task_id: string;
    agent_type: string;
    error: string;
    sub_query: string;
  }>;
}

export interface ApprovalStats {
  total_approvals: number;
  approved: number;
  modified: number;
  rejected: number;
  pending: number;
  avg_response_time_seconds: number;
  by_agent: Record<string, {
    approved: number;
    modified: number;
    rejected: number;
    pending: number;
  }>;
}

export interface AgentWorkload {
  [agentType: string]: {
    status: string;
    active_tasks: number;
    pending_tasks: number;
    total_load: number;
    historical_tasks?: number;
  };
}

export const getAdminStats = async (): Promise<AdminStats> => {
  const response = await client.get('/admin/stats');
  return response.data;
};

export const getEngagementData = async (): Promise<EngagementDataPoint[]> => {
  const response = await client.get('/admin/engagement');
  return response.data;
};

export const getIntentData = async (): Promise<IntentDataPoint[]> => {
  const response = await client.get('/admin/intents');
  return response.data;
};

// New API calls for enhanced dashboard
export const getSystemOverview = async (): Promise<SystemOverview> => {
  const response = await client.get('/admin/system-overview');
  return response.data;
};

export const getLLMUsageStats = async (): Promise<LLMUsageStats> => {
  const response = await client.get('/admin/llm-usage');
  return response.data;
};

export const getTaskPerformance = async (): Promise<TaskPerformance> => {
  const response = await client.get('/admin/task-performance');
  return response.data;
};

export const getApprovalStats = async (): Promise<ApprovalStats> => {
  const response = await client.get('/admin/approval-stats');
  return response.data;
};

export const getAgentWorkload = async (): Promise<AgentWorkload> => {
  const response = await client.get('/admin/agent-workload');
  return response.data;
};
