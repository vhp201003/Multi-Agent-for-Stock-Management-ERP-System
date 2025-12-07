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
 * Handles both metadata.layout and content parsing
 */
export const normalizeBackendMessage = (
  msg: ConversationMessage,
  messageId: string
): NormalizedMessage => {
  console.log('[normalizeBackendMessage] Processing message:', messageId);
  console.log('[normalizeBackendMessage] Message role:', msg.role);
  console.log('[normalizeBackendMessage] Message metadata:', msg.metadata);
  
  const normalized: NormalizedMessage = {
    id: messageId,
    type: msg.role as 'user' | 'assistant' | 'system',
    content: msg.content,
    timestamp: new Date(msg.timestamp),
  };

  // PRIORITY 1: Try to parse content as JSON first (for backward compatibility)
  // This handles old messages where layout+full_data are in content
  if (msg.content && msg.role === 'assistant') {
    console.log('[normalizeBackendMessage] Attempting to parse assistant content as JSON...');
    try {
      const parsed = JSON.parse(msg.content);
      console.log('[normalizeBackendMessage] Parsed content:', parsed);
      
      if (parsed.layout) {
        console.log('[normalizeBackendMessage] Found layout in content:', parsed.layout);
        normalized.layout = parsed.layout as LayoutField[];
        
        // Also extract full_data if available
        if (parsed.full_data) {
          console.log('[normalizeBackendMessage] Found full_data in content, processing...');
          normalized.layout = processLayoutWithFullData(
            normalized.layout,
            parsed.full_data
          );
          console.log('[normalizeBackendMessage] Processed layout from content:', normalized.layout);
        }
      }
    } catch (e) {
      // Content is not JSON, will try metadata next
      console.log('[normalizeBackendMessage] Content is not JSON:', e);
    }
  }

  // PRIORITY 2: Check metadata (for new messages with proper metadata storage)
  if (msg.metadata && !normalized.layout) {
    console.log('[normalizeBackendMessage] Checking metadata for layout...');
    
    // Case 1: Layout stored in metadata.layout
    if (msg.metadata.layout) {
      console.log('[normalizeBackendMessage] Found layout in metadata:', msg.metadata.layout);
      normalized.layout = msg.metadata.layout as LayoutField[];
    }
    
    // Case 2: Updates stored in metadata.updates (thinking process)
    if (msg.metadata.updates) {
      normalized.updates = msg.metadata.updates;
      normalized.isThinkingExpanded = false; // Collapsed by default for loaded messages
    }

    // Case 3: Check if metadata.full_data exists for data processing
    if (msg.metadata.full_data && normalized.layout) {
      console.log('[normalizeBackendMessage] Found full_data in metadata, processing layout...');
      console.log('[normalizeBackendMessage] full_data:', msg.metadata.full_data);
      // Process layout with full_data (similar to live response)
      normalized.layout = processLayoutWithFullData(
        normalized.layout,
        msg.metadata.full_data
      );
      console.log('[normalizeBackendMessage] Processed layout from metadata:', normalized.layout);
    } else {
      if (!msg.metadata.full_data && normalized.layout) {
        console.warn('[normalizeBackendMessage] Layout exists but no full_data in metadata');
      }
    }
  } else if (msg.metadata && normalized.layout) {
    console.log('[normalizeBackendMessage] Layout already populated from content, skipping metadata');
  } else if (!msg.metadata) {
    console.warn('[normalizeBackendMessage] No metadata found for message:', messageId);
  }

  console.log('[normalizeBackendMessage] Final normalized message has layout:', !!normalized.layout);
  if (normalized.layout) {
    console.log('[normalizeBackendMessage] Layout fields:', normalized.layout.map(f => f.field_type));
  }
  
  return normalized;
};

/**
 * Process layout fields with full_data to populate chart data
 * Unified algorithm for both live and loaded messages
 */
const processLayoutWithFullData = (
  layout: LayoutField[],
  fullData: Record<string, unknown>
): LayoutField[] => {
  console.log('[processLayoutWithFullData] Processing layout with full_data');
  console.log('[processLayoutWithFullData] Full data structure:', Object.keys(fullData));
  
  return layout.map((field, index) => {
    console.log(`[processLayoutWithFullData] Processing field ${index}:`, field.field_type);
    
    // Only process graph fields with data_source
    if (field.field_type !== 'graph' || !field.data_source) {
      console.log(`[processLayoutWithFullData] Skipping field ${index} - not a graph or no data_source`);
      return field;
    }

    const { data_source } = field;
    console.log('[processLayoutWithFullData] Graph field data_source:', data_source);

    // Extract data from full_data using data_path
    let sourceData: Record<string, unknown>[] = [];
    
    if (data_source.data_path && fullData) {
      console.log('[processLayoutWithFullData] Extracting data from path:', data_source.data_path);
      sourceData = extractDataByPath(fullData, data_source.data_path);
      console.log('[processLayoutWithFullData] Extracted source data length:', sourceData.length);
      if (sourceData.length > 0) {
        console.log('[processLayoutWithFullData] Sample data:', sourceData[0]);
      }
    } else if (fullData) {
      // Fallback: use full_data directly if it's an array
      console.log('[processLayoutWithFullData] No data_path, checking if fullData is array');
      sourceData = Array.isArray(fullData) ? fullData : [];
    }

    // Transform source data to chart format
    if (sourceData.length > 0 && data_source.label_field && data_source.value_field) {
      console.log('[processLayoutWithFullData] Transforming data to chart format...');
      console.log('[processLayoutWithFullData] Label field:', data_source.label_field);
      console.log('[processLayoutWithFullData] Value field:', data_source.value_field);
      
      const labels = sourceData.map(item => 
        String(item[data_source.label_field!] || '')
      );
      
      const values = sourceData.map(item => {
        const value = item[data_source.value_field!];
        return typeof value === 'number' ? value : Number(value) || 0;
      });

      console.log('[processLayoutWithFullData] Generated labels:', labels);
      console.log('[processLayoutWithFullData] Generated values:', values);

      // Populate field.data with chart-ready format
      return {
        ...field,
        data: {
          labels,
          datasets: [{
            label: data_source.value_field.replace(/_/g, ' ').toUpperCase(),
            data: values,
          }],
        },
      };
    }

    console.warn('[processLayoutWithFullData] No data found for graph field');
    return field;
  });
};

/**
 * Extract nested data from object using dot notation path
 * Example: "inventory.items" -> fullData.inventory.items
 */
const extractDataByPath = (obj: Record<string, unknown>, path: string): Record<string, unknown>[] => {
  console.log('[extractDataByPath] Extracting from path:', path);
  console.log('[extractDataByPath] Object keys:', Object.keys(obj));
  
  if (!path) {
    console.warn('[extractDataByPath] No path provided');
    return [];
  }
  
  const parts = path.split('.');
  console.log('[extractDataByPath] Path parts:', parts);
  
  let current: unknown = obj;
  
  for (const part of parts) {
    console.log('[extractDataByPath] Navigating to:', part);
    console.log('[extractDataByPath] Current type:', typeof current);
    
    if (current && typeof current === 'object' && part in current) {
      current = (current as Record<string, unknown>)[part];
      console.log('[extractDataByPath] Found, new current type:', typeof current);
    } else {
      console.warn('[extractDataByPath] Path part not found:', part);
      console.warn('[extractDataByPath] Available keys:', current && typeof current === 'object' ? Object.keys(current) : 'not an object');
      return [];
    }
  }
  
  const result = Array.isArray(current) ? current : [];
  console.log('[extractDataByPath] Final result is array:', Array.isArray(current), 'length:', result.length);
  
  return result;
};

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
