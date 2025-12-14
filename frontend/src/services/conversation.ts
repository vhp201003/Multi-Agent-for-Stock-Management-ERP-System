/**
 * Conversation API Service
 * Handles all conversation-related API calls for backend sync
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';

import type { LayoutField, TaskUpdate } from '../types/message';

export interface ConversationMessageMetadata {
  layout?: LayoutField[];
  updates?: TaskUpdate[];
  full_data?: Record<string, unknown>;
  message_id?: string;
  [key: string]: unknown;
}

export interface ConversationMessage {
  role: string;
  content: string;
  metadata?: ConversationMessageMetadata;
  timestamp: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages?: ConversationMessage[];
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
}

export interface QuickActionsResponse {
  conversation_id: string;
  suggestions: string[];
}

/**
 * Create a new conversation
 */
/**
 * Create a new conversation
 */
export const createConversation = async (
  conversationId: string,
  title?: string
): Promise<Conversation> => {
  const token = localStorage.getItem('token');
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      conversation_id: conversationId,
      title: title || `Conversation ${conversationId.slice(0, 8)}`,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to create conversation: ${response.statusText}`);
  }

  return response.json();
};

/**
 * Get a single conversation by ID
 */
export const getConversation = async (
  conversationId: string,
  includeMessages = true
): Promise<Conversation> => {
  const url = new URL(`${API_BASE}/conversations/${conversationId}`);
  if (includeMessages) {
    url.searchParams.set('include_messages', 'true');
  }

  const token = localStorage.getItem('token');
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url.toString(), { headers });

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    throw new Error(`Failed to get conversation: ${response.statusText}`);
  }

  return response.json();
};

/**
 * List all conversations with pagination
 */
export const listConversations = async (
  limit = 50,
  offset = 0
): Promise<ConversationListResponse> => {
  const url = new URL(`${API_BASE}/conversations`);
  url.searchParams.set('limit', limit.toString());
  url.searchParams.set('offset', offset.toString());

  const token = localStorage.getItem('token');
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url.toString(), { headers });

  if (!response.ok) {
    throw new Error(`Failed to list conversations: ${response.statusText}`);
  }

  return response.json();
};

/**
 * Update conversation title
 */
export const updateConversationTitle = async (
  conversationId: string,
  title: string
): Promise<Conversation> => {
  const token = localStorage.getItem('token');
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ title }),
  });

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    throw new Error(`Failed to update conversation: ${response.statusText}`);
  }

  return response.json();
};

/**
 * Delete a conversation
 */
export const deleteConversation = async (conversationId: string): Promise<void> => {
  const token = localStorage.getItem('token');
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'DELETE',
    headers,
  });

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    throw new Error(`Failed to delete conversation: ${response.statusText}`);
  }
};

/**
 * Get quick action suggestions for a conversation
 */
export const getQuickActions = async (
  conversationId: string
): Promise<QuickActionsResponse | null> => {
  const token = localStorage.getItem('token');
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${API_BASE}/conversations/${conversationId}/quick-actions`,
    { headers }
  );

  if (!response.ok) {
    // Return null if no quick actions available (404 or 500)
    console.warn(`Failed to get quick actions: ${response.statusText}`);
    return null;
  }

  const data = await response.json();

  // Return null if suggestions array is empty or null
  if (!data.suggestions || data.suggestions.length === 0) {
    return null;
  }

  return data;
};
