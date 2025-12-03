import React, { useEffect, useState, useCallback } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';
import { getSystemOverview, getAgentWorkload } from '../../services/admin';
import type { SystemOverview, AgentWorkload } from '../../services/admin';
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

const STATUS_COLORS: Record<string, string> = {
  idle: '#10b981',
  processing: '#f59e0b',
  error: '#ef4444',
  offline: '#6b7280',
};

const Integrations: React.FC = () => {
  const [systemOverview, setSystemOverview] = useState<SystemOverview | null>(null);
  const [agentWorkload, setAgentWorkload] = useState<AgentWorkload | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [overview, workload] = await Promise.all([
        getSystemOverview(),
        getAgentWorkload()
      ]);
      setSystemOverview(overview);
      setAgentWorkload(workload);
    } catch (error) {
      console.error('Failed to fetch integrations data:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Refresh every 10 seconds for real-time status
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return <div className="page-loading">Loading agents status...</div>;
  }

  const workloadChartData = Object.entries(agentWorkload || {}).map(([name, data]) => ({
    name: name.replace('_agent', '').replace('_', ' '),
    active: data.active_tasks,
    pending: data.pending_tasks,
    historical: data.historical_tasks || 0,
  }));

  const onlineAgents = systemOverview?.agents.filter(a => a.status !== 'offline').length || 0;
  const totalAgents = systemOverview?.agents.length || 0;

  return (
    <div className="admin-page">
      <div className="page-header">
        <div>
          <h1>Agent Integrations</h1>
          <p>Multi-agent system status and workload monitoring</p>
        </div>
        <button className="refresh-btn" onClick={fetchData}>🔄 Refresh</button>
      </div>

      {/* System Status Summary */}
      <section className="page-section">
        <h2 className="section-title">System Status</h2>
        <div className="metrics-grid four-cols">
          <div className="metric-card">
            <div className="metric-icon">🤖</div>
            <div className="metric-content">
              <div className="metric-value">{onlineAgents}/{totalAgents}</div>
              <div className="metric-label">Agents Online</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📋</div>
            <div className="metric-content">
              <div className="metric-value">{systemOverview?.active_queries || 0}</div>
              <div className="metric-label">Active Queries</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📥</div>
            <div className="metric-content">
              <div className="metric-value">{systemOverview?.total_queued_tasks || 0}</div>
              <div className="metric-label">Queued Tasks</div>
            </div>
          </div>
          <div className="metric-card warning">
            <div className="metric-icon">⚠️</div>
            <div className="metric-content">
              <div className="metric-value">{systemOverview?.pending_approvals || 0}</div>
              <div className="metric-label">Pending Approvals</div>
            </div>
          </div>
        </div>
      </section>

      {/* Agent Status Grid */}
      <section className="page-section">
        <h2 className="section-title">Agent Status</h2>
        <div className="agents-grid">
          {systemOverview?.agents.map((agent) => (
            <div key={agent.agent_type} className={`agent-card ${agent.status}`}>
              <div className="agent-header">
                <span className="agent-status-dot" style={{ backgroundColor: STATUS_COLORS[agent.status] || STATUS_COLORS.offline }} />
                <span className="agent-name">{agent.agent_type.replace('_agent', '').replace('_', ' ')}</span>
                <span className={`agent-status-badge ${agent.status}`}>{agent.status}</span>
              </div>
              <div className="agent-description">
                {getAgentDescription(agent.agent_type)}
              </div>
              <div className="agent-stats">
                <div className="agent-stat">
                  <span className="stat-number">{agent.queue_size}</span>
                  <span className="stat-label">Active</span>
                </div>
                <div className="agent-stat">
                  <span className="stat-number">{agent.pending_queue_size}</span>
                  <span className="stat-label">Pending</span>
                </div>
                <div className="agent-stat">
                  <span className="stat-number">{agentWorkload?.[agent.agent_type]?.historical_tasks || 0}</span>
                  <span className="stat-label">Total</span>
                </div>
              </div>
              <div className="agent-color-indicator" style={{ backgroundColor: AGENT_COLORS[agent.agent_type] || '#6b7280' }} />
            </div>
          ))}
        </div>
      </section>

      {/* Workload Chart */}
      <section className="page-section">
        <h2 className="section-title">Workload Distribution</h2>
        <div className="chart-card full-width">
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={workloadChartData}>
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
                <Legend />
                <Bar dataKey="active" name="Active Tasks" fill="#3b82f6" stackId="current" />
                <Bar dataKey="pending" name="Pending Tasks" fill="#f59e0b" stackId="current" />
                <Bar dataKey="historical" name="Historical" fill="#6b7280" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      {/* Agent Capabilities */}
      <section className="page-section">
        <h2 className="section-title">Agent Capabilities</h2>
        <div className="capabilities-grid">
          {systemOverview?.agents.map((agent) => (
            <div key={agent.agent_type} className="capability-card">
              <div className="capability-header">
                <span className="capability-icon">{getAgentIcon(agent.agent_type)}</span>
                <span className="capability-name">{agent.agent_type.replace('_agent', '').replace('_', ' ')}</span>
              </div>
              <div className="capability-list">
                {getAgentCapabilities(agent.agent_type).map((cap, idx) => (
                  <div key={idx} className="capability-item">
                    <span className="cap-check">✓</span>
                    <span>{cap}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};

function getAgentDescription(agentType: string): string {
  const descriptions: Record<string, string> = {
    orchestrator: 'Routes queries and coordinates multi-agent workflows',
    inventory_agent: 'Manages stock levels, products, and warehouse data',
    analytics_agent: 'Analyzes sales trends, revenue, and business metrics',
    forecasting_agent: 'Predicts demand and generates stock forecasts',
    ordering_agent: 'Handles purchase orders and supplier management',
    summary_agent: 'Synthesizes results from multiple agents',
    chat_agent: 'Handles general conversations and FAQs',
  };
  return descriptions[agentType] || 'AI agent for specialized tasks';
}

function getAgentIcon(agentType: string): string {
  const icons: Record<string, string> = {
    orchestrator: '🎯',
    inventory_agent: '📦',
    analytics_agent: '📊',
    forecasting_agent: '🔮',
    ordering_agent: '🛒',
    summary_agent: '📝',
    chat_agent: '💬',
  };
  return icons[agentType] || '🤖';
}

function getAgentCapabilities(agentType: string): string[] {
  const caps: Record<string, string[]> = {
    orchestrator: ['Query classification', 'Task decomposition', 'Agent routing', 'Result aggregation'],
    inventory_agent: ['Stock lookup', 'Product search', 'Inventory alerts', 'Warehouse management'],
    analytics_agent: ['Sales analysis', 'Revenue reports', 'Trend detection', 'Performance metrics'],
    forecasting_agent: ['Demand prediction', 'Stock forecasting', 'Seasonal analysis', 'Risk assessment'],
    ordering_agent: ['Purchase orders', 'Supplier queries', 'Reorder suggestions', 'Order tracking'],
    summary_agent: ['Result synthesis', 'Report generation', 'Key insights', 'Action recommendations'],
    chat_agent: ['FAQ handling', 'General queries', 'Conversation memory', 'Context awareness'],
  };
  return caps[agentType] || ['General AI capabilities'];
}

export default Integrations;
