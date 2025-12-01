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
