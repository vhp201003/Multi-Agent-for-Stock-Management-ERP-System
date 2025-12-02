import React, { useState, useCallback, useEffect, useMemo } from 'react';
import type { ApprovalRequest, ApprovalResponse, ApprovalAction } from '../types/approval';
import './ApprovalModal.css';

interface ApprovalModalProps {
  approval: ApprovalRequest;
  onRespond: (response: ApprovalResponse) => void;
  onClose?: () => void;
}

/**
 * Modal component for Human-in-the-Loop approval workflow
 * 
 * Displays approval request with:
 * - Tool name and agent info
 * - Proposed parameters (editable if in modifiable_fields)
 * - Countdown timer
 * - Approve/Modify/Reject buttons
 */
const ApprovalModal: React.FC<ApprovalModalProps> = ({ approval, onRespond, onClose }) => {
  const [modifiedParams, setModifiedParams] = useState<Record<string, unknown>>({});
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [timeLeft, setTimeLeft] = useState<number>(approval.timeout_seconds);

  // Initialize modified params with proposed values
  useEffect(() => {
    const initialModified: Record<string, unknown> = {};
    approval.modifiable_fields.forEach((field) => {
      if (field in approval.proposed_params) {
        initialModified[field] = approval.proposed_params[field];
      }
    });
    setModifiedParams(initialModified);
  }, [approval]);

  // Countdown timer
  useEffect(() => {
    const createdAt = new Date(approval.created_at).getTime();
    const expiresAt = createdAt + approval.timeout_seconds * 1000;

    const updateTimer = () => {
      const now = Date.now();
      const remaining = Math.max(0, Math.floor((expiresAt - now) / 1000));
      setTimeLeft(remaining);

      if (remaining === 0) {
        // Auto-timeout - close modal
        onClose?.();
      }
    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [approval, onClose]);

  // Check if params were modified
  const hasModifications = useMemo(() => {
    return Object.entries(modifiedParams).some(([key, value]) => {
      return value !== approval.proposed_params[key];
    });
  }, [modifiedParams, approval.proposed_params]);

  // Handle field change
  const handleFieldChange = useCallback((field: string, value: unknown) => {
    setModifiedParams((prev) => ({
      ...prev,
      [field]: value,
    }));
  }, []);

  // Handle approve
  const handleApprove = useCallback(() => {
    const action: ApprovalAction = hasModifications ? 'modify' : 'approve';
    
    onRespond({
      approval_id: approval.approval_id,
      query_id: approval.query_id,
      action,
      modified_params: hasModifications ? modifiedParams : undefined,
    });
  }, [approval, hasModifications, modifiedParams, onRespond]);

  // Handle reject
  const handleReject = useCallback(() => {
    if (!showRejectInput) {
      setShowRejectInput(true);
      return;
    }

    onRespond({
      approval_id: approval.approval_id,
      query_id: approval.query_id,
      action: 'reject',
      reason: rejectReason || 'User rejected',
    });
  }, [approval, showRejectInput, rejectReason, onRespond]);

  // Format field name for display
  const formatFieldName = (field: string): string => {
    return field
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());
  };

  // Render field input based on value type
  const renderFieldInput = (field: string, value: unknown, isModifiable: boolean) => {
    const currentValue = isModifiable ? modifiedParams[field] ?? value : value;

    if (typeof value === 'boolean') {
      return (
        <label className="approval-checkbox">
          <input
            type="checkbox"
            checked={!!currentValue}
            disabled={!isModifiable}
            onChange={(e) => handleFieldChange(field, e.target.checked)}
          />
          <span>{currentValue ? 'Yes' : 'No'}</span>
        </label>
      );
    }

    if (typeof value === 'number') {
      return (
        <input
          type="number"
          className="approval-input"
          value={currentValue as number}
          disabled={!isModifiable}
          onChange={(e) => handleFieldChange(field, parseFloat(e.target.value) || 0)}
        />
      );
    }

    if (Array.isArray(value)) {
      return (
        <textarea
          className="approval-textarea"
          value={JSON.stringify(currentValue, null, 2)}
          disabled={!isModifiable}
          onChange={(e) => {
            try {
              handleFieldChange(field, JSON.parse(e.target.value));
            } catch {
              // Invalid JSON, ignore
            }
          }}
        />
      );
    }

    if (typeof value === 'object' && value !== null) {
      return (
        <pre className="approval-json">
          {JSON.stringify(currentValue, null, 2)}
        </pre>
      );
    }

    // String or other
    return (
      <input
        type="text"
        className="approval-input"
        value={String(currentValue ?? '')}
        disabled={!isModifiable}
        onChange={(e) => handleFieldChange(field, e.target.value)}
      />
    );
  };

  // Format time remaining
  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="approval-overlay">
      <div className="approval-modal">
        {/* Header */}
        <div className="approval-header">
          <div className="approval-title-section">
            <span className="approval-icon">🔐</span>
            <div>
              <h3 className="approval-title">{approval.title}</h3>
              <p className="approval-subtitle">
                <span className="approval-agent">{approval.agent_type}</span>
                <span className="approval-separator">→</span>
                <span className="approval-tool">{approval.tool_name}</span>
              </p>
            </div>
          </div>
          <div className={`approval-timer ${timeLeft < 30 ? 'warning' : ''} ${timeLeft < 10 ? 'critical' : ''}`}>
            ⏱️ {formatTime(timeLeft)}
          </div>
        </div>

        {/* Description */}
        {approval.description && (
          <p className="approval-description">{approval.description}</p>
        )}

        {/* Parameters */}
        <div className="approval-params">
          <h4>Parameters</h4>
          <div className="approval-params-list">
            {Object.entries(approval.proposed_params).map(([field, value]) => {
              const isModifiable = approval.modifiable_fields.includes(field);
              return (
                <div key={field} className={`approval-param ${isModifiable ? 'modifiable' : ''}`}>
                  <label className="approval-param-label">
                    {formatFieldName(field)}
                    {isModifiable && <span className="editable-badge">✏️ Editable</span>}
                  </label>
                  <div className="approval-param-value">
                    {renderFieldInput(field, value, isModifiable)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Reject reason input */}
        {showRejectInput && (
          <div className="approval-reject-section">
            <label>Rejection reason (optional):</label>
            <textarea
              className="approval-reject-input"
              placeholder="Why are you rejecting this action?"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              autoFocus
            />
          </div>
        )}

        {/* Actions */}
        <div className="approval-actions">
          <button 
            className="approval-btn approve"
            onClick={handleApprove}
          >
            {hasModifications ? '✏️ Modify & Approve' : '✅ Approve'}
          </button>
          
          <button 
            className="approval-btn reject"
            onClick={handleReject}
          >
            {showRejectInput ? '❌ Confirm Reject' : '❌ Reject'}
          </button>
        </div>

        {/* Modifiable fields hint */}
        {approval.modifiable_fields.length > 0 && (
          <p className="approval-hint">
            💡 You can modify: {approval.modifiable_fields.map(formatFieldName).join(', ')}
          </p>
        )}
      </div>
    </div>
  );
};

export default ApprovalModal;
