import React, { useEffect, useState } from 'react';
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
import { getAdminStats, getEngagementData, getIntentData } from '../services/admin';
import type { AdminStats, EngagementDataPoint, IntentDataPoint } from '../services/admin';
import './Dashboard.css';

const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [engagementData, setEngagementData] = useState<EngagementDataPoint[]>([]);
  const [intentData, setIntentData] = useState<IntentDataPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsData, engagement, intents] = await Promise.all([
          getAdminStats(),
          getEngagementData(),
          getIntentData()
        ]);
        setStats(statsData);
        setEngagementData(engagement);
        setIntentData(intents);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return <div className="dashboard-loading">Loading dashboard data...</div>;
  }

  const statCards = [
    { 
      title: 'Total Users', 
      value: stats?.total_users.toLocaleString() || '0', 
      change: stats?.stats_change.total_users || '0%', 
      isPositive: (stats?.stats_change.total_users || '').startsWith('+') 
    },
    { 
      title: 'Active Conversations', 
      value: stats?.active_conversations.toLocaleString() || '0', 
      change: stats?.stats_change.active_conversations || '0%', 
      isPositive: (stats?.stats_change.active_conversations || '').startsWith('+') 
    },
    { 
      title: 'Message Volume', 
      value: stats?.message_volume.toLocaleString() || '0', 
      change: stats?.stats_change.message_volume || '0%', 
      isPositive: (stats?.stats_change.message_volume || '').startsWith('+') 
    },
    { 
      title: 'Resolution Rate', 
      value: `${stats?.resolution_rate || 0}%`, 
      change: stats?.stats_change.resolution_rate || '0%', 
      isPositive: (stats?.stats_change.resolution_rate || '').startsWith('+') 
    },
  ];

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1>Welcome back, Admin!</h1>
        <p>Here's a snapshot of your chatbot's performance today.</p>
        <button className="view-reports-btn">View Reports</button>
      </div>

      <div className="stats-grid">
        {statCards.map((stat, index) => (
          <div key={index} className="stat-card">
            <div className="stat-title">{stat.title}</div>
            <div className="stat-value">{stat.value}</div>
            <div className={`stat-change ${stat.isPositive ? 'positive' : 'negative'}`}>
              {stat.change}
            </div>
          </div>
        ))}
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <div className="chart-header">
            <h3>User Engagement</h3>
            <div className="chart-metric">{engagementData.reduce((acc, curr) => acc + curr.value, 0).toLocaleString()}</div>
            <div className="chart-subtext">Last 30 Days</div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={engagementData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                <XAxis dataKey="name" stroke="#666" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                  itemStyle={{ color: '#fff' }}
                />
                <Line 
                  type="monotone" 
                  dataKey="value" 
                  stroke="#2196f3" 
                  strokeWidth={3} 
                  dot={false} 
                  activeDot={{ r: 6 }} 
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="chart-card">
          <div className="chart-header">
            <h3>Common User Intents</h3>
            <div className="chart-metric">{intentData.reduce((acc, curr) => acc + curr.value, 0).toLocaleString()}</div>
            <div className="chart-subtext">Top Categories</div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={intentData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                <XAxis dataKey="name" stroke="#666" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip 
                  cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }}
                  contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                  itemStyle={{ color: '#fff' }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {intentData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill="#263238" />
                  ))}
                  {/* Highlight specific bars if needed, or use a single color. 
                      The design shows dark blue bars. I'll use a nice blue-grey. 
                      Actually, let's make the highest one brighter or something. 
                      For now, uniform color. */}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
