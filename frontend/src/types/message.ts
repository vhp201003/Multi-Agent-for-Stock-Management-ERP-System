/**
 * Shared TypeScript types for frontend components
 */

export interface ChartDataSource {
  agent_type: string;
  tool_name: string;
  label_field: string;
  value_field: string;
  data_path?: string;
}

export interface LayoutField {
  field_type: string;
  title?: string;
  description?: string;
  content?: string;
  graph_type?: string;
  data_source?: ChartDataSource;
  data?: {
    headers?: string[];
    rows?: unknown[][];
    labels?: string[];
    datasets?: Array<{
      label: string;
      data: unknown[];
    }>;
  };
}

export interface TaskUpdate {
  agent_type: string;
  step?: string;
  status: 'processing' | 'done' | 'failed';
  message?: string;
  sub_query?: string;
  result?: any;
  llm_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

export interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  updates?: TaskUpdate[];
  layout?: LayoutField[];
  isThinkingExpanded?: boolean;
}
