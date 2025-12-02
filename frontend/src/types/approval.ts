/**
 * Approval types for Human-in-the-Loop workflow
 */

export type ApprovalAction = 'approve' | 'modify' | 'reject';

export type ApprovalLevel = 'none' | 'confirm' | 'review';

export interface ApprovalRequest {
  approval_id: string;
  query_id: string;
  task_id?: string;
  agent_type: string;
  tool_name: string;
  proposed_params: Record<string, unknown>;
  title: string;
  description?: string;
  modifiable_fields: string[];
  timeout_seconds: number;
  created_at: string;
}

export interface ApprovalResponse {
  approval_id: string;
  query_id: string;
  action: ApprovalAction;
  modified_params?: Record<string, unknown>;
  reason?: string;
  responded_at?: string;
}
