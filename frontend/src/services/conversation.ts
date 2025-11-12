/**
 * Conversation API Service
 * Handles all conversation-related API calls for backend sync
 */

const API_BASE = 'http://localhost:8010';

export interface ConversationMessage {
  role: string;
  content: string;
  metadata?: Record<string, any>;
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

/**
 * Create a new conversation
 */
export const createConversation = async (
  conversationId: string,
  title?: string
): Promise<Conversation> => {
  const response = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
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

  const response = await fetch(url.toString());

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

  const response = await fetch(url.toString());

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
  const response = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
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
  const response = await fetch(`${API_BASE}/conversations/${conversationId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Conversation not found');
    }
    throw new Error(`Failed to delete conversation: ${response.statusText}`);
  }
};
