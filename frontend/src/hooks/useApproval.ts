import { useState, useCallback, useEffect, useRef } from 'react';
import type { ApprovalRequest, ApprovalResponse, ApprovalAction } from '../types/approval';

interface UseApprovalOptions {
  onApprovalRequest?: (request: ApprovalRequest) => void;
  onApprovalResolved?: (approvalId: string, action: ApprovalAction) => void;
}

interface UseApprovalReturn {
  pendingApprovals: ApprovalRequest[];
  respond: (response: ApprovalResponse) => void;
  handleApprovalMessage: (data: ApprovalRequest) => void;
  handleApprovalResolved: (data: { approval_id: string; action: ApprovalAction }) => void;
  clearApprovals: () => void;
}

/**
 * Hook to manage Human-in-the-Loop approval workflow
 * 
 * Usage:
 * ```tsx
 * const { pendingApprovals, respond, handleApprovalMessage } = useApproval({
 *   onApprovalRequest: (req) => console.log('New approval:', req),
 * });
 * 
 * // In WebSocket message handler:
 * if (message.type === 'approval_required') {
 *   handleApprovalMessage(message.data);
 * }
 * ```
 */
export function useApproval(options: UseApprovalOptions = {}): UseApprovalReturn {
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  // Handle incoming approval request
  const handleApprovalMessage = useCallback((data: ApprovalRequest) => {
    setPendingApprovals((prev) => {
      // Avoid duplicates
      if (prev.some((a) => a.approval_id === data.approval_id)) {
        return prev;
      }
      return [...prev, data];
    });

    options.onApprovalRequest?.(data);
  }, [options]);

  // Handle approval resolved (from backend confirmation)
  const handleApprovalResolved = useCallback((data: { approval_id: string; action: ApprovalAction }) => {
    setPendingApprovals((prev) => 
      prev.filter((a) => a.approval_id !== data.approval_id)
    );
    
    options.onApprovalResolved?.(data.approval_id, data.action);
  }, [options]);

  // Send approval response
  const respond = useCallback((response: ApprovalResponse) => {
    // Remove from pending immediately for responsive UI
    setPendingApprovals((prev) => 
      prev.filter((a) => a.approval_id !== response.approval_id)
    );

    // Send to backend via WebSocket
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'approval_response',
        data: {
          ...response,
          responded_at: new Date().toISOString(),
        },
      }));
    } else {
      console.warn('[useApproval] WebSocket not connected, cannot send response');
    }
  }, []);

  // Clear all pending approvals
  const clearApprovals = useCallback(() => {
    setPendingApprovals([]);
  }, []);

  // Auto-timeout handling
  useEffect(() => {
    const checkTimeouts = () => {
      const now = Date.now();
      
      setPendingApprovals((prev) => {
        const stillValid = prev.filter((approval) => {
          const createdAt = new Date(approval.created_at).getTime();
          const expiresAt = createdAt + approval.timeout_seconds * 1000;
          return now < expiresAt;
        });
        
        // Log expired approvals
        const expired = prev.filter((a) => !stillValid.includes(a));
        expired.forEach((a) => {
          console.log(`[useApproval] Approval ${a.approval_id} expired`);
        });
        
        return stillValid;
      });
    };

    const interval = setInterval(checkTimeouts, 5000); // Check every 5s
    return () => clearInterval(interval);
  }, []);

  return {
    pendingApprovals,
    respond,
    handleApprovalMessage,
    handleApprovalResolved,
    clearApprovals,
  };
}

export default useApproval;
