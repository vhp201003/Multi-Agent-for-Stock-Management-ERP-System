import React from 'react';
import { Outlet } from 'react-router-dom';
import AdminSidebar from '../components/AdminSidebar';
import './AdminLayout.css';

const AdminLayout: React.FC = () => {
  return (
    <div className="admin-layout">
      <AdminSidebar />
      <div className="admin-content">
        <header className="admin-header">
          <div className="header-title">Dashboard</div>
          <div className="header-actions">
            <div className="search-bar">
              <span className="search-icon">🔍</span>
              <input type="text" placeholder="Search" />
            </div>
            <button className="icon-btn">🔔</button>
            <button className="icon-btn">⚙️</button>
            <div className="user-avatar">👤</div>
          </div>
        </header>
        <main className="admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default AdminLayout;
