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

// Reasoning step from orchestrator CoT
export interface ReasoningStep {
  step: string;
  explanation: string;
  conclusion: string;
}

export interface TaskUpdate {
  agent_type: string;
  step?: string;
  status: 'processing' | 'done' | 'failed' | 'pending_approval' | 'auto_approved';
  type?: 'approval_required' | 'reasoning_step';
  approval?: any;
  message?: string;
  sub_query?: string;
  result?: any;
  // Reasoning step data (orchestrator CoT)
  step_number?: number;
  total_steps?: number;
  explanation?: string;
  conclusion?: string;
  llm_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  timestamp?: string;
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
