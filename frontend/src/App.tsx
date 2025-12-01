import { useState } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import ChatInterface from './components/ChatInterface'
import { AuthProvider, useAuth } from './context/AuthContext'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import AdminLayout from './layouts/AdminLayout'
import Dashboard from './pages/Dashboard'
import './App.css'

const PrivateRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />;
};

function MainLayout() {
  const [currentConversationId, setCurrentConversationId] = useState<string>('')

  const handleSelectConversation = (conversationId: string) => {
    setCurrentConversationId(conversationId)
  }

  const handleNewConversation = () => {
    setCurrentConversationId('')
  }

  return (
    <div className="app">
      <Sidebar 
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        currentConversationId={currentConversationId}
      />
      <ChatInterface conversationId={currentConversationId} />
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={
            <PrivateRoute>
              <MainLayout />
            </PrivateRoute>
          } />
          <Route path="/admin" element={
            <PrivateRoute>
              <AdminLayout />
            </PrivateRoute>
          }>
            <Route index element={<Dashboard />} />
            {/* Add other admin routes here as placeholders */}
            <Route path="users" element={<div>Users Page (Coming Soon)</div>} />
            <Route path="settings" element={<div>Settings Page (Coming Soon)</div>} />
            <Route path="analytics" element={<div>Analytics Page (Coming Soon)</div>} />
            <Route path="integrations" element={<div>Integrations Page (Coming Soon)</div>} />
          </Route>
        </Routes>
      </Router>
    </AuthProvider>
  )
}

export default App
