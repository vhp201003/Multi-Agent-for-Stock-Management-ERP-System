import React, { useEffect, useState, useCallback } from 'react';
import { getAdminStats } from '../../services/admin';
import type { AdminStats } from '../../services/admin';
import './AdminPages.css';

interface UserInfo {
  id: string;
  email: string;
  username: string;
  role: string;
  created_at: string;
  conversations_count: number;
  messages_count: number;
  last_active: string;
}

const Users: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchData = useCallback(async () => {
    try {
      const statsData = await getAdminStats();
      setStats(statsData);
      
      // Mock users for now - in production, this would come from an API
      // You can add a /admin/users endpoint later
      setUsers([
        {
          id: '1',
          email: 'admin@example.com',
          username: 'admin',
          role: 'admin',
          created_at: '2024-01-15',
          conversations_count: 45,
          messages_count: 320,
          last_active: '2 hours ago'
        },
        {
          id: '2',
          email: 'user@example.com',
          username: 'john_doe',
          role: 'user',
          created_at: '2024-02-20',
          conversations_count: 12,
          messages_count: 87,
          last_active: '1 day ago'
        },
      ]);
    } catch (error) {
      console.error('Failed to fetch users:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const filteredUsers = users.filter(user =>
    user.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    user.username.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) {
    return <div className="page-loading">Loading users...</div>;
  }

  return (
    <div className="admin-page">
      <div className="page-header">
        <div>
          <h1>User Management</h1>
          <p>Manage users and view conversation history</p>
        </div>
        <button className="primary-btn">+ Add User</button>
      </div>

      {/* User Stats */}
      <section className="page-section">
        <div className="metrics-grid four-cols">
          <div className="metric-card">
            <div className="metric-icon">👥</div>
            <div className="metric-content">
              <div className="metric-value">{stats?.total_users || 0}</div>
              <div className="metric-label">Total Users</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">💬</div>
            <div className="metric-content">
              <div className="metric-value">{stats?.active_conversations || 0}</div>
              <div className="metric-label">Conversations</div>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-icon">📨</div>
            <div className="metric-content">
              <div className="metric-value">{stats?.message_volume || 0}</div>
              <div className="metric-label">Total Messages</div>
            </div>
          </div>
          <div className="metric-card success">
            <div className="metric-icon">🟢</div>
            <div className="metric-content">
              <div className="metric-value">{stats?.total_users || 0}</div>
              <div className="metric-label">Active Today</div>
            </div>
          </div>
        </div>
      </section>

      {/* User List */}
      <section className="page-section">
        <div className="section-header">
          <h2 className="section-title">All Users</h2>
          <div className="search-input">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              placeholder="Search users..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        <div className="data-table">
          <div className="table-header">
            <span>User</span>
            <span>Role</span>
            <span>Conversations</span>
            <span>Messages</span>
            <span>Joined</span>
            <span>Last Active</span>
            <span>Actions</span>
          </div>
          {filteredUsers.length > 0 ? (
            filteredUsers.map((user) => (
              <div key={user.id} className="table-row">
                <span className="user-cell">
                  <div className="user-avatar">{user.username.charAt(0).toUpperCase()}</div>
                  <div className="user-info">
                    <div className="user-name">{user.username}</div>
                    <div className="user-email">{user.email}</div>
                  </div>
                </span>
                <span>
                  <span className={`role-badge ${user.role}`}>{user.role}</span>
                </span>
                <span>{user.conversations_count}</span>
                <span>{user.messages_count}</span>
                <span>{user.created_at}</span>
                <span className="last-active">{user.last_active}</span>
                <span className="actions-cell">
                  <button className="action-btn" title="View">👁️</button>
                  <button className="action-btn" title="Edit">✏️</button>
                  <button className="action-btn danger" title="Delete">🗑️</button>
                </span>
              </div>
            ))
          ) : (
            <div className="empty-state">
              <div className="empty-icon">👥</div>
              <div className="empty-text">No users found</div>
            </div>
          )}
        </div>
      </section>

      {/* Recent Activity */}
      <section className="page-section">
        <h2 className="section-title">Recent Activity</h2>
        <div className="activity-list">
          <div className="activity-item">
            <span className="activity-icon">💬</span>
            <div className="activity-content">
              <div className="activity-text"><strong>admin</strong> started a new conversation</div>
              <div className="activity-time">2 hours ago</div>
            </div>
          </div>
          <div className="activity-item">
            <span className="activity-icon">📊</span>
            <div className="activity-content">
              <div className="activity-text"><strong>john_doe</strong> queried analytics data</div>
              <div className="activity-time">1 day ago</div>
            </div>
          </div>
          <div className="activity-item">
            <span className="activity-icon">✅</span>
            <div className="activity-content">
              <div className="activity-text"><strong>admin</strong> approved an order request</div>
              <div className="activity-time">2 days ago</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default Users;
