import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LineChart,
  Line,
  XAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell
} from 'recharts';
import {
  getAdminStats,
  getEngagementData,
  getIntentData,
  getSystemOverview,
  getLLMUsageStats,
  getTaskPerformance
} from '../services/admin';
import type {
  AdminStats,
  EngagementDataPoint,
  IntentDataPoint,
  SystemOverview,
  LLMUsageStats,
  TaskPerformance
} from '../services/admin';
import './Dashboard.css';

const AGENT_COLORS: Record<string, string> = {
  orchestrator: '#8b5cf6',
  inventory_agent: '#3b82f6',
  analytics_agent: '#10b981',
  forecasting_agent: '#f59e0b',
  ordering_agent: '#ef4444',
  summary_agent: '#ec4899',
  chat_agent: '#06b6d4',
};

const STATUS_COLORS: Record<string, string> = {
  idle: '#10b981',
  processing: '#f59e0b',
  error: '#ef4444',
  offline: '#6b7280',
};

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [engagementData, setEngagementData] = useState<EngagementDataPoint[]>([]);
  const [intentData, setIntentData] = useState<IntentDataPoint[]>([]);
  const [systemOverview, setSystemOverview] = useState<SystemOverview | null>(null);
  const [llmUsage, setLLMUsage] = useState<LLMUsageStats | null>(null);
  const [taskPerf, setTaskPerf] = useState<TaskPerformance | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [statsData, engagement, intents, sysOverview, llm, taskPerformance] = await Promise.all([
        getAdminStats(),
        getEngagementData(),
        getIntentData(),
        getSystemOverview(),
        getLLMUsageStats(),
        getTaskPerformance()
      ]);
      setStats(statsData);
      setEngagementData(engagement);
      setIntentData(intents);
      setSystemOverview(sysOverview);
      setLLMUsage(llm);
      setTaskPerf(taskPerformance);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
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
    return <div className="dashboard-loading">Loading dashboard data...</div>;
  }

  const onlineAgents = systemOverview?.agents.filter(a => a.status !== 'offline').length || 0;
  const totalAgents = systemOverview?.agents.length || 0;

  const statCards = [
    { title: 'Total Users', value: stats?.total_users.toLocaleString() || '0', icon: '👥', link: '/admin/users' },
    { title: 'Conversations', value: stats?.active_conversations.toLocaleString() || '0', icon: '💬', link: '/admin/users' },
    { title: 'Messages', value: stats?.message_volume.toLocaleString() || '0', icon: '📨', link: '/admin/analytics' },
    { title: 'Success Rate', value: `${taskPerf?.success_rate || 0}%`, icon: '✅', link: '/admin/analytics' },
  ];

  return (
    <div className="dashboard-container">
      {/* Header */}
      <div className="dashboard-header">
        <div className="header-left">
          <h1>Dashboard</h1>
          <p>Multi-Agent System Overview</p>
        </div>
        <button className="refresh-btn" onClick={fetchData}>🔄 Refresh</button>
      </div>

      {/* System Status Bar */}
      <div className="system-status-bar">
        <div className="status-item clickable" onClick={() => navigate('/admin/integrations')}>
          <span className="status-label">Agents Online</span>
          <span className="status-value">{onlineAgents}/{totalAgents}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Active Queries</span>
          <span className="status-value">{systemOverview?.active_queries || 0}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Queued Tasks</span>
          <span className="status-value">{systemOverview?.total_queued_tasks || 0}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Pending Approvals</span>
          <span className={`status-value ${(systemOverview?.pending_approvals || 0) > 0 ? 'warning' : ''}`}>
            {systemOverview?.pending_approvals || 0}
          </span>
        </div>
        <div className="status-item clickable" onClick={() => navigate('/admin/analytics')}>
          <span className="status-label">Total Tokens</span>
          <span className="status-value">{llmUsage?.total_tokens.toLocaleString() || 0}</span>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="stats-grid">
        {statCards.map((stat, index) => (
          <div key={index} className="stat-card clickable" onClick={() => navigate(stat.link)}>
            <div className="stat-icon">{stat.icon}</div>
            <div className="stat-content">
              <div className="stat-title">{stat.title}</div>
              <div className="stat-value">{stat.value}</div>
            </div>
            <div className="stat-arrow">→</div>
          </div>
        ))}
      </div>

      {/* Quick Stats Row */}
      <div className="quick-stats-row">
        <div className="quick-stat">
          <span className="quick-stat-icon">🔥</span>
          <span className="quick-stat-value">{llmUsage?.total_requests || 0}</span>
          <span className="quick-stat-label">LLM Requests</span>
        </div>
        <div className="quick-stat">
          <span className="quick-stat-icon">⚡</span>
          <span className="quick-stat-value">{llmUsage?.avg_response_time_ms.toFixed(0) || 0}ms</span>
          <span className="quick-stat-label">Avg Response</span>
        </div>
        <div className="quick-stat success">
          <span className="quick-stat-icon">✅</span>
          <span className="quick-stat-value">{taskPerf?.completed_tasks || 0}</span>
          <span className="quick-stat-label">Completed</span>
        </div>
        <div className="quick-stat error">
          <span className="quick-stat-icon">❌</span>
          <span className="quick-stat-value">{taskPerf?.failed_tasks || 0}</span>
          <span className="quick-stat-label">Failed</span>
        </div>
        <div className="quick-stat warning">
          <span className="quick-stat-icon">⏳</span>
          <span className="quick-stat-value">{taskPerf?.pending_tasks || 0}</span>
          <span className="quick-stat-label">Pending</span>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="charts-grid">
        {/* Engagement Chart */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>User Engagement</h3>
            <div className="chart-metric">
              {engagementData.reduce((acc, curr) => acc + curr.value, 0).toLocaleString()}
            </div>
            <div className="chart-subtext">Messages last 30 days</div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={engagementData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-primary)" vertical={false} />
                <XAxis dataKey="name" stroke="var(--text-secondary)" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <Tooltip contentStyle={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)', borderRadius: '8px' }} itemStyle={{ color: 'var(--text-primary)' }} />
                <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Intent Distribution */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Agent Usage</h3>
            <div className="chart-metric">
              {intentData.reduce((acc, curr) => acc + curr.value, 0).toLocaleString()}
            </div>
            <div className="chart-subtext">Requests by agent type</div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={intentData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-primary)" horizontal={false} />
                <XAxis type="number" stroke="var(--text-secondary)" tick={{ fontSize: 10 }} />
                <Tooltip contentStyle={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)', borderRadius: '8px' }} itemStyle={{ color: 'var(--text-primary)' }} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {intentData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={Object.values(AGENT_COLORS)[index % Object.values(AGENT_COLORS).length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Agent Status Mini Grid */}
      <div className="section">
        <div className="section-header-row">
          <h2 className="section-title">Agent Status</h2>
          <button className="view-all-btn" onClick={() => navigate('/admin/integrations')}>View All →</button>
        </div>
        <div className="agents-mini-grid">
          {systemOverview?.agents.slice(0, 4).map((agent) => (
            <div key={agent.agent_type} className="agent-mini-card">
              <span className="agent-status-dot" style={{ backgroundColor: STATUS_COLORS[agent.status] || STATUS_COLORS.offline }} />
              <span className="agent-mini-name">{agent.agent_type.replace('_agent', '').replace('_', ' ')}</span>
              <span className={`agent-mini-status ${agent.status}`}>{agent.status}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Quick Links */}
      <div className="quick-links">
        <div className="quick-link" onClick={() => navigate('/admin/analytics')}>
          <span className="link-icon">📊</span>
          <span className="link-text">View Analytics</span>
        </div>
        <div className="quick-link" onClick={() => navigate('/admin/users')}>
          <span className="link-icon">👥</span>
          <span className="link-text">Manage Users</span>
        </div>
        <div className="quick-link" onClick={() => navigate('/admin/integrations')}>
          <span className="link-icon">🤖</span>
          <span className="link-text">Agent Details</span>
        </div>
        <div className="quick-link" onClick={() => navigate('/admin/settings')}>
          <span className="link-icon">⚙️</span>
          <span className="link-text">Settings</span>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
