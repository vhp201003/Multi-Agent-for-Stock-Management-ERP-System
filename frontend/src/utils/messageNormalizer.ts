/**
 * Message Normalization Utilities
 * Ensures consistent message format for both live WebSocket and loaded backend data
 */

import type { LayoutField, TaskUpdate } from '../types/message';
import type { ConversationMessage } from '../services/conversation';

export interface NormalizedMessage {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  layout?: LayoutField[];
  updates?: TaskUpdate[];
  isThinkingExpanded?: boolean;
}

/**
 * Normalize a message from backend storage to UI format
 * - content = layout JSON
 * - metadata = full_data only
 */
export const normalizeBackendMessage = (
  msg: ConversationMessage,
  messageId: string
): NormalizedMessage => {
  const normalized: NormalizedMessage = {
    id: messageId,
    type: msg.role as 'user' | 'assistant' | 'system',
    content: msg.content,
    timestamp: new Date(msg.timestamp),
  };

  if (msg.role !== 'assistant') {
    return normalized;
  }

  // Parse content JSON to get layout
  let layout: LayoutField[] | undefined;
  if (msg.content) {
    try {
      const parsed = JSON.parse(msg.content);
      if (parsed.layout) {
        layout = parsed.layout as LayoutField[];
      }
    } catch {
      // Content is not JSON (old format or plain text)
    }
  }

  // Get full_data from metadata
  const fullData = msg.metadata?.full_data;

  // Process layout with full_data if both exist
  if (layout) {
    if (fullData) {
      normalized.layout = processLayoutWithData(layout, fullData);
    } else {
      normalized.layout = layout;
    }
  }

  // Handle updates (thinking process)
  if (msg.metadata?.updates) {
    normalized.updates = msg.metadata.updates;
    normalized.isThinkingExpanded = false;
  }
  
  return normalized;
};

/**
 * Process layout fields with full_data to populate chart data
 * Unified algorithm for both live and loaded messages
 */
import { processLayoutWithData } from './chartDataExtractor';

/**
 * Normalize messages from localStorage (legacy format)
 * Maintains backward compatibility
 */
export const normalizeLocalStorageMessages = (
  messages: Record<string, unknown>[]
): NormalizedMessage[] => {
  return messages.map((msg, index) => ({
    id: (msg.id as string) || `msg-${index}`,
    type: (msg.type as 'user' | 'assistant' | 'system') || 'user',
    content: (msg.content as string) || '',
    timestamp: msg.timestamp ? new Date(msg.timestamp as string) : new Date(),
    layout: msg.layout as LayoutField[] | undefined,
    updates: msg.updates as TaskUpdate[] | undefined,
    isThinkingExpanded: msg.isThinkingExpanded as boolean | undefined,
  }));
};

/**
 * Convert backend conversation messages to normalized format
 */
export const normalizeConversationMessages = (
  messages: ConversationMessage[]
): NormalizedMessage[] => {
  return messages.map((msg, index) => 
    normalizeBackendMessage(msg, msg.metadata?.message_id || `msg-${index}`)
  );
};
