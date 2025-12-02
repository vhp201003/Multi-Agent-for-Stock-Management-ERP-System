import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';

// Helper function to generate unique IDs
export const generateId = (): string => {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

// HITL Mode types
export type HITLMode = 'review' | 'auto';

export interface UserSettings {
  hitl_mode: HITLMode;
}

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

  async getMe(token: string): Promise<any> {
    const response = await this.client.get('/auth/me', {
      headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
  }

  async login(data: any): Promise<any> {
    // Form data for OAuth2
    const formData = new FormData();
    formData.append('username', data.email);
    formData.append('password', data.password);
    
    const response = await this.client.post('/auth/token', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  }

  async register(data: any): Promise<any> {
    const response = await this.client.post('/auth/register', data);
    return response.data;
  }

  async submitQuery(queryId: string, query: string, conversationId?: string): Promise<QueryResponse> {
    const token = localStorage.getItem('token');
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    
    const requestData: QueryRequest = {
      query_id: queryId,
      query,
      ...(conversationId && { conversation_id: conversationId }),
    };
    
    const response = await this.client.post<QueryResponse>('/query', requestData, { headers });
    return response.data;
  }

  async getQueryStatus(queryId: string): Promise<QueryStatus> {
    const token = localStorage.getItem('token');
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const response = await this.client.get<QueryStatus>(`/query/${queryId}`, { headers });
    return response.data;
  }

  async checkHealth(): Promise<{ status: string }> {
    const response = await this.client.get<{ status: string }>('/health');
    return response.data;
  }

  async getUserSettings(token: string): Promise<UserSettings> {
    const response = await this.client.get<UserSettings>('/auth/settings', {
      headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
  }

  async updateUserSettings(token: string, settings: Partial<UserSettings>): Promise<UserSettings> {
    const response = await this.client.patch<UserSettings>('/auth/settings', settings, {
      headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
  }
}

export const apiService = new ApiService();
