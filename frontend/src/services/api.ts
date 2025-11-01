import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';

// Helper function to generate unique IDs
export const generateId = (): string => {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

export interface QueryRequest {
  query_id: string;  // Frontend tạo và gửi
  query: string;
  conversation_id?: string;  // Gửi từ message thứ 2 trở đi
}

export interface QueryResponse {
  query_id: string;
  conversation_id?: string;
  status: string;
  message: string;
}

export interface TaskUpdate {
  status: string;
  agent_type?: string;
  step?: string;
  message?: string;
  sub_query?: string;
  result?: any; // Can be string or object with tool_results, agents_needed, etc.
  llm_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  timestamp?: string;
}

export interface QueryStatus {
  query_id: string;
  conversation_id: string;
  status: string;
  query_text: string;
  result?: string;
  final_answer?: string;
  task_updates?: TaskUpdate[];
}

class ApiService {
  private client = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  async submitQuery(queryId: string, query: string, conversationId?: string): Promise<QueryResponse> {
    const requestData: QueryRequest = {
      query_id: queryId,
      query,
      ...(conversationId && { conversation_id: conversationId }),
    };
    
    const response = await this.client.post<QueryResponse>('/query', requestData);
    return response.data;
  }

  async getQueryStatus(queryId: string): Promise<QueryStatus> {
    const response = await this.client.get<QueryStatus>(`/query/${queryId}`);
    return response.data;
  }

  async checkHealth(): Promise<{ status: string }> {
    const response = await this.client.get<{ status: string }>('/health');
    return response.data;
  }
}

export const apiService = new ApiService();
