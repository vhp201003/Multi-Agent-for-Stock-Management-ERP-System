import React, { useEffect, useState, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie,
  Legend
} from 'recharts';
import {
  getLLMUsageStats,
  getTaskPerformance,
  getApprovalStats,
  getEngagementData
} from '../../services/admin';
import type {
  LLMUsageStats,
  TaskPerformance,
  ApprovalStats,
  EngagementDataPoint
} from '../../services/admin';
import './AdminPages.css';

const AGENT_COLORS: Record<string, string> = {
  orchestrator: '#8b5cf6',
  inventory_agent: '#3b82f6',
  analytics_agent: '#10b981',
  forecasting_agent: '#f59e0b',
  ordering_agent: '#ef4444',
  summary_agent: '#ec4899',
  chat_agent: '#06b6d4',
};

const Analytics: React.FC = () => {
  const [llmUsage, setLLMUsage] = useState<LLMUsageStats | null>(null);
  const [taskPerf, setTaskPerf] = useState<TaskPerformance | null>(null);
  const [approvalStats, setApprovalStats] = useState<ApprovalStats | null>(null);
  const [engagementData, setEngagementData] = useState<EngagementDataPoint[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [llm, tasks, approvals, engagement] = await Promise.all([
        getLLMUsageStats(),
        getTaskPerformance(),
        getApprovalStats(),
        getEngagementData()
      ]);
      setLLMUsage(llm);
      setTaskPerf(tasks);
      setApprovalStats(approvals);
      setEngagementData(engagement);
    } catch (error) {
      console.error('Failed to fetch analytics:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return <div className="page-loading">Loading analytics...</div>;
  }

  const llmByAgentData = llmUsage?.usage_by_agent
    ? Object.entries(llmUsage.usage_by_agent).map(([name, data]) => ({
        name: name.replace('_agent', '').replace('_', ' '),
        tokens: data.total_tokens,
        requests: data.requests,
        avgTime: data.avg_response_time_ms,
      }))
    : [];

  const taskDistributionData = taskPerf?.tasks_by_agent
    ? Object.entries(taskPerf.tasks_by_agent).map(([name, data]) => ({
        name: name.replace('_agent', '').replace('_', ' '),
        value: data.completed + data.failed + data.pending,
      }))
    : [];

  const approvalPieData = approvalStats
    ? [
        { name: 'Approved', value: approvalStats.approved, color: '#10b981' },
        { name: 'Modified', value: approvalStats.modified, color: '#f59e0b' },
        { name: 'Rejected', value: approvalStats.rejected, color: '#ef4444' },
        { name: 'Pending', value: approvalStats.pending, color: '#6b7280' },
      ].filter(d => d.value > 0)
    : [];

  return (
    <div className="admin-page">
      <div className="page-header">
        <div>
          <h1>Analytics</h1>
          <p>LLM usage, task performance, and system metrics</p>
        </div>
        <button className="refresh-btn" onClick={fetchData}>🔄 Refresh</button>
      </div>

      {/* LLM Usage Stats */}
      <section className="page-section">
        <h2 className="section-title">LLM Usage</h2>
        <div className="metrics-grid">
          <div className="metric-card highlight">
            <div className="metric-icon">🔥</div>
            <div className="metric-content">
              <div className="metric-value">{llmUsage?.total_tokens.toLocaleString() || 0}</div>
              <div className="metric-label">Total Tokens</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📥</div>
            <div className="metric-content">
              <div className="metric-value">{llmUsage?.total_prompt_tokens.toLocaleString() || 0}</div>
              <div className="metric-label">Prompt Tokens</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📤</div>
            <div className="metric-content">
              <div className="metric-value">{llmUsage?.total_completion_tokens.toLocaleString() || 0}</div>
              <div className="metric-label">Completion Tokens</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">⚡</div>
            <div className="metric-content">
              <div className="metric-value">{llmUsage?.avg_response_time_ms.toFixed(0) || 0}ms</div>
              <div className="metric-label">Avg Response Time</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📊</div>
            <div className="metric-content">
              <div className="metric-value">{llmUsage?.total_requests.toLocaleString() || 0}</div>
              <div className="metric-label">Total Requests</div>
            </div>
          </div>
        </div>

        <div className="charts-row">
          <div className="chart-card">
            <h3>Token Usage by Agent</h3>
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={llmByAgentData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-primary)" vertical={false} />
                  <XAxis dataKey="name" stroke="var(--text-secondary)" tick={{ fontSize: 11 }} />
                  <YAxis stroke="var(--text-secondary)" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-primary)',
                      borderRadius: '8px'
                    }}
                    itemStyle={{ color: 'var(--text-primary)' }}
                  />
                  <Bar dataKey="tokens" name="Tokens" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                    {llmByAgentData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={Object.values(AGENT_COLORS)[index % Object.values(AGENT_COLORS).length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="chart-card">
            <h3>Response Time by Agent (ms)</h3>
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={llmByAgentData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-primary)" horizontal={false} />
                  <XAxis type="number" stroke="var(--text-secondary)" tick={{ fontSize: 10 }} />
                  <YAxis dataKey="name" type="category" stroke="var(--text-secondary)" tick={{ fontSize: 11 }} width={80} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-primary)',
                      borderRadius: '8px'
                    }}
                  />
                  <Bar dataKey="avgTime" name="Avg Time (ms)" fill="#10b981" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* LLM Usage Table */}
        {llmUsage?.usage_by_agent && Object.keys(llmUsage.usage_by_agent).length > 0 && (
          <div className="data-table">
            <div className="table-header">
              <span>Agent</span>
              <span>Requests</span>
              <span>Prompt</span>
              <span>Completion</span>
              <span>Total</span>
              <span>Avg Time</span>
            </div>
            {Object.entries(llmUsage.usage_by_agent).map(([agent, data]) => (
              <div key={agent} className="table-row">
                <span className="agent-cell">
                  <span className="agent-dot" style={{ backgroundColor: AGENT_COLORS[agent] || '#6b7280' }} />
                  {agent.replace('_agent', '')}
                </span>
                <span>{data.requests}</span>
                <span>{data.prompt_tokens.toLocaleString()}</span>
                <span>{data.completion_tokens.toLocaleString()}</span>
                <span className="highlight">{data.total_tokens.toLocaleString()}</span>
                <span>{data.avg_response_time_ms.toFixed(0)}ms</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Task Performance */}
      <section className="page-section">
        <h2 className="section-title">Task Performance</h2>
        <div className="metrics-grid four-cols">
          <div className="metric-card success">
            <div className="metric-icon">✅</div>
            <div className="metric-content">
              <div className="metric-value">{taskPerf?.completed_tasks || 0}</div>
              <div className="metric-label">Completed</div>
            </div>
          </div>
          <div className="metric-card error">
            <div className="metric-icon">❌</div>
            <div className="metric-content">
              <div className="metric-value">{taskPerf?.failed_tasks || 0}</div>
              <div className="metric-label">Failed</div>
            </div>
          </div>
          <div className="metric-card warning">
            <div className="metric-icon">⏳</div>
            <div className="metric-content">
              <div className="metric-value">{taskPerf?.pending_tasks || 0}</div>
              <div className="metric-label">Pending</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📈</div>
            <div className="metric-content">
              <div className="metric-value">{taskPerf?.success_rate || 0}%</div>
              <div className="metric-label">Success Rate</div>
            </div>
          </div>
        </div>

        <div className="charts-row">
          <div className="chart-card">
            <h3>Task Distribution by Agent</h3>
            <div className="chart-container pie-container">
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={taskDistributionData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    dataKey="value"
                    label={(props: Record<string, unknown>) => `${props.name} ${((props.percent as number) * 100).toFixed(0)}%`}
                  >
                    {taskDistributionData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={Object.values(AGENT_COLORS)[index % Object.values(AGENT_COLORS).length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="chart-card">
            <h3>Message Engagement (30 Days)</h3>
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={engagementData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-primary)" vertical={false} />
                  <XAxis dataKey="name" stroke="var(--text-secondary)" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                  <YAxis stroke="var(--text-secondary)" tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-primary)',
                      borderRadius: '8px'
                    }}
                  />
                  <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Agent Performance Breakdown */}
        {taskPerf?.tasks_by_agent && (
          <div className="agent-perf-grid">
            {Object.entries(taskPerf.tasks_by_agent).map(([agent, data]) => {
              const total = data.completed + data.failed + data.pending;
              const successRate = total > 0 ? ((data.completed / total) * 100).toFixed(1) : 0;
              return (
                <div key={agent} className="agent-perf-card">
                  <div className="agent-perf-header">
                    <span className="agent-color-bar" style={{ backgroundColor: AGENT_COLORS[agent] || '#6b7280' }} />
                    <span className="agent-perf-name">{agent.replace('_agent', '').replace('_', ' ')}</span>
                  </div>
                  <div className="agent-perf-stats">
                    <div className="perf-stat success"><span>{data.completed}</span><label>Done</label></div>
                    <div className="perf-stat error"><span>{data.failed}</span><label>Fail</label></div>
                    <div className="perf-stat warning"><span>{data.pending}</span><label>Wait</label></div>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill success" style={{ width: `${total > 0 ? (data.completed / total) * 100 : 0}%` }} />
                    <div className="progress-fill error" style={{ width: `${total > 0 ? (data.failed / total) * 100 : 0}%` }} />
                  </div>
                  <div className="agent-perf-rate">{successRate}% success</div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* HITL Approval Stats */}
      {approvalStats && approvalStats.total_approvals > 0 && (
        <section className="page-section">
          <h2 className="section-title">HITL Approval Statistics</h2>
          <div className="charts-row">
            <div className="chart-card">
              <h3>Approval Outcomes</h3>
              <div className="approval-summary">
                <div className="approval-total">{approvalStats.total_approvals} total</div>
                <div className="approval-avg">Avg response: {approvalStats.avg_response_time_seconds}s</div>
              </div>
              <div className="chart-container pie-container">
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={approvalPieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} dataKey="value">
                      {approvalPieData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="chart-card">
              <h3>Approvals by Agent</h3>
              <div className="approval-agent-list">
                {Object.entries(approvalStats.by_agent).map(([agent, data]) => (
                  <div key={agent} className="approval-agent-item">
                    <span className="agent-name">{agent.replace('_agent', '')}</span>
                    <div className="approval-badges">
                      <span className="badge approved">{data.approved} ✓</span>
                      <span className="badge modified">{data.modified} ✎</span>
                      <span className="badge rejected">{data.rejected} ✗</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Recent Errors */}
      {taskPerf?.recent_errors && taskPerf.recent_errors.length > 0 && (
        <section className="page-section">
          <h2 className="section-title">Recent Errors</h2>
          <div className="errors-list">
            {taskPerf.recent_errors.map((error, index) => (
              <div key={index} className="error-item">
                <div className="error-header">
                  <span className="error-agent">{error.agent_type}</span>
                  <span className="error-task-id">{error.task_id}</span>
                </div>
                <div className="error-message">{error.error}</div>
                <div className="error-query">{error.sub_query}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

export default Analytics;
