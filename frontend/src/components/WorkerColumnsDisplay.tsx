import React, { useEffect, useState } from 'react';
import type { TaskUpdate } from '../types/message';
import './WorkerColumnsDisplay.css';

interface WorkerColumn {
  agent_type: string;
  updates: TaskUpdate[];
  status: 'idle' | 'processing' | 'done' | 'failed';
}

interface WorkerColumnsDisplayProps {
  agents_needed: string[];
  messageUpdates: TaskUpdate[];
  isComplete: boolean;
}

/**
 * Displays parallel worker execution in side-by-side columns
 * Shows thinking progress of each worker type independently
 */
export const WorkerColumnsDisplay: React.FC<WorkerColumnsDisplayProps> = ({
  agents_needed,
  messageUpdates,
  isComplete,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const [orchestratorExpanded, setOrchestratorExpanded] = useState(true);

  // Filter updates
  const orchestratorUpdates = messageUpdates.filter(
    (u) => u.agent_type === 'orchestrator'
  );

  // Group updates by agent_type for other workers
  const getWorkerColumns = (): WorkerColumn[] => {
    const columns: Map<string, WorkerColumn> = new Map();

    // Initialize columns for each agent_type (excluding orchestrator)
    agents_needed
      .filter((agent) => agent !== 'orchestrator')
      .forEach((agent) => {
        columns.set(agent, {
          agent_type: agent,
          updates: [],
          status: 'idle',
        });
      });

    // Distribute updates to corresponding columns
    messageUpdates.forEach((update) => {
      // Skip orchestrator updates here
      if (update.agent_type === 'orchestrator') return;

      if (update.agent_type && columns.has(update.agent_type)) {
        const column = columns.get(update.agent_type)!;
        column.updates.push(update);

        // Update status logic
        // 1. If we see a 'failed' status, marks as failed immediately
        if (update.status === 'failed') {
          column.status = 'failed';
        }
        // 2. If we see 'done', mark as done (unless already failed)
        else if ((update.status === 'done' || update.status === 'auto_approved') && column.status !== 'failed') {
          column.status = 'done';
        }
        // 3. If currently idle/processing, update to processing (unless already done/failed)
        else if (update.status === 'processing' && column.status !== 'done' && column.status !== 'failed') {
          column.status = 'processing';
        }
      }
    });

    // Post-processing: If overall task is complete, force all non-failed workers to 'done'
    // This fixes cases where the last message was 'thinking' but the backend finished the task.
    if (isComplete) {
      for (const column of columns.values()) {
        if (column.status !== 'failed') {
          column.status = 'done';
        }
      }
    }

    return Array.from(columns.values());
  };

  const getAgentDisplayName = (agent_type: string): string => {
    const names: Record<string, string> = {
      orchestrator: 'Orchestrator',
      inventory: 'Inventory Manager',
      forecasting: 'Forecasting Analyst',
      analytics: 'Data Analytics',
      ordering: 'Order Management',
      chat: 'Chat Assistant',
    };
    return names[agent_type] || agent_type;
  };

  const getStatusLabel = (status: string): string => {
    const labels: Record<string, string> = {
      idle: 'Pending',
      processing: 'Processing...',
      done: 'Completed',
      failed: 'Failed',
    };
    return labels[status] || status;
  };

  const columns = getWorkerColumns();

  // Summary for collapsed state
  const activeWorkers = columns.filter(c => c.status === 'processing').length;
  const completedWorkers = columns.filter(c => c.status === 'done').length;
  const totalWorkers = columns.length;
  const summaryText = isComplete 
    ? "Completed successfully" 
    : `Processing: ${activeWorkers}/${totalWorkers} agents active`;

  return (
    <div className="worker-columns-container">
      {/* Main Header / Toggle */}
      <div 
        className="main-workflow-header"
        onClick={() => setIsExpanded(!isExpanded)}
        role="button"
        tabIndex={0}
      >
        <div className="header-left">
          <span className="header-title">Thinking</span>
        </div>
      </div>

      {isExpanded && (
        <div className="workflow-content">
          {/* Orchestrator Section - Always at Top */}
          {orchestratorUpdates.length > 0 && (
            <div className="orchestrator-section">
              <div
                className="orchestrator-header"
                onClick={() => setOrchestratorExpanded(!orchestratorExpanded)}
                role="button"
                tabIndex={0}
              >
                <span className="section-title">Orchestrator Analysis</span>
              </div>
              {orchestratorExpanded && (
                <div className="orchestrator-body">
                  {orchestratorUpdates.map((update, idx) => (
                    <div key={idx} className="orchestrator-update">
                      {/* Primary Message / Thinking */}
                      {(update.message || update.reasoning) && (
                        <div className="message-content">
                          {update.reasoning ? (
                            <div className="thinking-block">
                              <span className="icon" title="Analysis">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                                  <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                                  <line x1="12" y1="22.08" x2="12" y2="12"></line>
                                </svg>
                              </span>
                              <span className="text">{update.reasoning}</span>
                            </div>
                          ) : (
                            <div className="message-text">{update.message}</div>
                          )}
                        </div>
                      )}

                      {/* Orchestrator CoT details */}
                      {update.explanation && (
                        <div className="detail-block">
                          <span className="icon" title="Logic">
                             <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                               <path d="M12 2a10 10 0 1 0 10 10 10 10 0 0 0-10-10zm-1 15v-4h2v4h-2zm-1-8.5a1.5 1.5 0 0 1 3 0 1.5 1.5 0 0 1-1.5 1.5v1h-2v-1a3.5 3.5 0 0 0-3.5-3.5h0z"/>
                             </svg>
                          </span>
                          <span className="text">{update.explanation}</span>
                        </div>
                      )}

                      {/* Plan */}
                      {update.agents_needed && (
                        <div className="plan-block">
                          <span className="icon" title="Workflow">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
                              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
                            </svg>
                          </span>
                          <span className="text">
                            Assigning to <span className="highlight-agents">{update.agents_needed.join(', ')}</span>
                          </span>
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Dynamic Task Breakdown (Derived from Worker Updates) */}
                  {/* Task Breakdown from Orchestrator Plan */}
                  {(() => {
                    const planUpdate = orchestratorUpdates.find(u => u.task_dependency && Object.keys(u.task_dependency).length > 0);

                    if (planUpdate && planUpdate.task_dependency) {
                      return (
                         <div className="plan-block subtasks-container">
                          <span className="icon" title="Sub-tasks">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M9 6h11M9 12h11M9 18h11M5 6v.01M5 12v.01M5 18v.01"></path>
                            </svg>
                          </span>
                          <div className="text">
                            <div className="subtasks-title">Task Breakdown:</div>
                            <div className="subtasks-list">
                              {Object.entries(planUpdate.task_dependency).flatMap(([agent, tasks]) => {
                                const taskList = Array.isArray(tasks) ? tasks : [tasks];
                                return taskList.map((task: any, idx: number) => (
                                  <div key={`${agent}-${idx}`} className="subtask-item">
                                    <span className="agent-badge">{getAgentDisplayName(agent)}</span>
                                    <span className="task-query">{task.sub_query || "Processing..."}</span>
                                  </div>
                                ));
                              })}
                            </div>
                          </div>
                        </div>
                      );
                    }
                    return null;
                  })()}
                </div>
              )}
            </div>
          )}

          {/* Parallel Workers Grid */}
          <div className="workers-section">
            <div
              className="workers-header"
            >
              <span className="section-title">
                Agent Operations
              </span>
            </div>

            <div className="columns-grid">
              {columns.map((column) => (
                <div
                  key={column.agent_type}
                  className={`worker-column ${column.status} ${
                    isComplete && column.agent_type === 'chat' ? 'highlight' : ''
                  }`}
                >
                  {/* Column Header */}
                  <div className="column-header">
                    <span className="agent-name">{getAgentDisplayName(column.agent_type)}</span>
                    <span className={`status-indicator ${column.status}`}>
                       {getStatusLabel(column.status)}
                    </span>
                  </div>

                  {/* Column Body */}
                  <div className="column-body">
                    {column.updates.length === 0 ? (
                      <div className="no-updates">Waiting for task...</div>
                    ) : (
                      <div className="updates-list">
                        {column.updates.map((update, idx) => (
                          <div
                            key={idx}
                            className={`update-item ${update.status}`}
                            style={{ animationDelay: `${idx * 50}ms` }}
                          >
                            {/* Update Content */}
                            <div className="update-content">
                              {update.message && (
                                <div className="update-message">
                                  <span className="step-number">{idx + 1}</span>
                                  <span className="message-text">{update.message}</span>
                                </div>
                              )}
                              {update.sub_query && (
                                <div className="metadata-row">
                                  <span className="meta-label">Query:</span> {update.sub_query}
                                </div>
                              )}
                              {update.step && (
                                <div className="metadata-row">
                                  <span className="meta-label">Action:</span> {update.step}
                                </div>
                              )}
                            </div>

                            {/* Tool Results */}
                            {update.result && typeof update.result === 'object' && (
                              <div className="tool-result">
                                <details>
                                  <summary>
                                    View Output ({Object.keys(update.result).length} fields)
                                  </summary>
                                  <pre>{JSON.stringify(update.result, null, 2)}</pre>
                                </details>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Completion Status */}
                    {column.status === 'done' && column.updates.length > 0 && (
                      <div className="status-banner success">Task Completed</div>
                    )}
                    {column.status === 'failed' && column.updates.length > 0 && (
                      <div className="status-banner error">Task Failed</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
