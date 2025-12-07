import React, { useState, useCallback, useEffect, useMemo } from "react";
import type {
  ApprovalRequest,
  ApprovalResponse,
  ApprovalAction,
} from "../types/approval";
import "./ApprovalCard.css";

interface ApprovalCardProps {
  approval: ApprovalRequest;
  onRespond: (response: ApprovalResponse) => void;
  isResolved?: boolean;
  resolvedAction?: ApprovalAction;
}

const ApprovalCard: React.FC<ApprovalCardProps> = ({
  approval,
  onRespond,
  isResolved = false,
  resolvedAction,
}) => {
  const [modifiedParams, setModifiedParams] = useState<Record<string, unknown>>(
    {}
  );
  const [timeLeft, setTimeLeft] = useState<number>(approval.timeout_seconds);
  const [isExpired, setIsExpired] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Initialize modified params
  useEffect(() => {
    const initial: Record<string, unknown> = {};
    approval.modifiable_fields.forEach((field) => {
      if (field in approval.proposed_params) {
        initial[field] = approval.proposed_params[field];
      }
    });
    setModifiedParams(initial);
  }, [approval]);

  // Countdown timer
  useEffect(() => {
    if (isResolved) return;

    const createdAt = new Date(approval.created_at).getTime();
    const expiresAt = createdAt + approval.timeout_seconds * 1000;

    const tick = () => {
      const remaining = Math.max(
        0,
        Math.floor((expiresAt - Date.now()) / 1000)
      );
      setTimeLeft(remaining);

      if (remaining === 0 && !isExpired) {
        setIsExpired(true);
        onRespond({
          approval_id: approval.approval_id,
          query_id: approval.query_id,
          action: "reject",
          reason: "Timeout",
        });
      }
    };

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [approval, isResolved, isExpired, onRespond]);

  const hasModifications = useMemo(() => {
    return Object.entries(modifiedParams).some(
      ([k, v]) => v !== approval.proposed_params[k]
    );
  }, [modifiedParams, approval.proposed_params]);

  const handleFieldChange = useCallback((field: string, value: unknown) => {
    setModifiedParams((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleApprove = useCallback(() => {
    if (isResolved || isExpired || isSubmitting) return;

    setIsSubmitting(true);
    console.log("[ApprovalCard] 🔔 Approving:", approval.approval_id);

    onRespond({
      approval_id: approval.approval_id,
      query_id: approval.query_id,
      action: hasModifications ? "modify" : "approve",
      modified_params: hasModifications ? modifiedParams : undefined,
    });

    // Reset submitting after a delay (in case backend doesn't respond)
    setTimeout(() => setIsSubmitting(false), 5000);
  }, [
    approval,
    hasModifications,
    modifiedParams,
    onRespond,
    isResolved,
    isExpired,
    isSubmitting,
  ]);

  const handleReject = useCallback(() => {
    if (isResolved || isExpired || isSubmitting) return;

    setIsSubmitting(true);
    console.log("[ApprovalCard] ❌ Rejecting:", approval.approval_id);

    onRespond({
      approval_id: approval.approval_id,
      query_id: approval.query_id,
      action: "reject",
      reason: "User rejected",
    });

    // Reset submitting after a delay
    setTimeout(() => setIsSubmitting(false), 5000);
  }, [approval, onRespond, isResolved, isExpired, isSubmitting]);

  const formatFieldName = (f: string) =>
    f.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  const formatTime = (s: number) =>
    `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;

  const statusClass = isResolved
    ? resolvedAction === "reject"
      ? "rejected"
      : "approved"
    : isExpired
    ? "expired"
    : "pending";

  return (
    <div className={`approval-card ${statusClass}`}>
      {/* Header row */}
      <div className="approval-card-row">
        <span className="approval-card-agent">{approval.agent_type}</span>
        <span className="approval-card-tool">{approval.tool_name}</span>
        {!isResolved && !isExpired && (
          <span
            className={`approval-card-timer ${timeLeft < 30 ? "warn" : ""}`}
          >
            {formatTime(timeLeft)}
          </span>
        )}
        {isResolved && (
          <span className={`approval-card-badge ${resolvedAction}`}>
            {resolvedAction === "approve" && "✓ Approved"}
            {resolvedAction === "modify" && "✓ Modified"}
            {resolvedAction === "reject" && "✗ Rejected"}
          </span>
        )}
        {isExpired && !isResolved && (
          <span className="approval-card-badge expired">Expired</span>
        )}
      </div>

      {/* Description */}
      {approval.description && (
        <div className="approval-card-desc">{approval.description}</div>
      )}

      {/* Params */}
      <div className="approval-card-params">
        {Object.entries(approval.proposed_params).map(([field, value]) => {
          const editable = approval.modifiable_fields.includes(field);
          const current = editable ? modifiedParams[field] ?? value : value;
          const disabled = !editable || isResolved || isExpired;

          return (
            <div
              key={field}
              className={`approval-card-param ${editable ? "editable" : ""}`}
            >
              <span className="param-label">{formatFieldName(field)}</span>
              {editable && !isResolved && !isExpired && (
                <span className="param-tag">editable</span>
              )}
              <input
                type={typeof value === "number" ? "number" : "text"}
                className="param-input"
                value={
                  typeof current === "object"
                    ? JSON.stringify(current)
                    : String(current ?? "")
                }
                disabled={disabled}
                onChange={(e) => {
                  const v =
                    typeof value === "number"
                      ? parseFloat(e.target.value) || 0
                      : e.target.value;
                  handleFieldChange(field, v);
                }}
              />
            </div>
          );
        })}
      </div>

      {/* Actions */}
      {!isResolved && !isExpired && (
        <div className="approval-card-actions">
          <button
            className="btn-approve"
            onClick={handleApprove}
            disabled={isSubmitting}
          >
            {isSubmitting
              ? "⏳ Processing..."
              : hasModifications
              ? "Modify & Approve"
              : "Approve"}
          </button>
          <button
            className="btn-reject"
            onClick={handleReject}
            disabled={isSubmitting}
          >
            {isSubmitting ? "⏳ Processing..." : "Reject"}
          </button>
        </div>
      )}
    </div>
  );
};

export default ApprovalCard;
