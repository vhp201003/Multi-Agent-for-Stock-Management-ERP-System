/**
 * Shared TypeScript types for frontend components
 */

export interface ChartDataSource {
  agent_type: string;
  tool_name: string;
  label_field?: string;
  value_field?: string;
  category_field?: string;
  x_field?: string;
  y_field?: string;
  name_field?: string;
  group_field?: string;
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
    // Legacy format (barchart, linechart, piechart)
    headers?: string[];
    rows?: unknown[][];
    labels?: string[];
    datasets?: Array<{
      label: string;
      data: unknown[];
    }>;
    // Recharts format (horizontalbarchart)
    chartData?: Array<{
      name: string;
      value: number;
      [key: string]: any;
    }>;
    dataKey?: string;
    nameKey?: string;
    layout?: 'horizontal' | 'vertical';
    // ScatterPlot format
    scatterData?: Array<{
      x: number;
      y: number;
      name?: string;
      group?: string;
      [key: string]: any;
    }>;
    xKey?: string;
    yKey?: string;
    groupKey?: string;
    groups?: string[];
    // Pagination support for tables
    totalItems?: number;
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
  // Orchestrator planning info
  agents_needed?: string[];
  task_dependency?: Record<string, any>;
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
