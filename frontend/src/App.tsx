import { useState, useEffect } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useParams,
} from "react-router-dom";
import Sidebar from "./components/Sidebar";
import ChatInterface from "./components/ChatInterface";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import AdminLayout from "./layouts/AdminLayout";
import Dashboard from "./pages/Dashboard";
import WorkerDashboard from "./pages/WorkerDashboard";
import { Analytics, Integrations, Users, Settings } from "./pages/admin";
import "./App.css";

const PrivateRoute: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />;
};

function MainLayout() {
  const navigate = useNavigate();
  const { conversationId: urlConversationId } = useParams();
  const [currentConversationId, setCurrentConversationId] = useState<string>(
    urlConversationId || ""
  );
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Sync URL with conversation ID
  useEffect(() => {
    if (urlConversationId && urlConversationId !== currentConversationId) {
      setCurrentConversationId(urlConversationId);
    }
  }, [urlConversationId]);

  const handleSelectConversation = (conversationId: string) => {
    setCurrentConversationId(conversationId);
    navigate(`/chat/${conversationId}`);
  };

  const handleNewConversation = () => {
    setCurrentConversationId("");
    navigate("/");
  };

  const handleConversationChange = (conversationId: string) => {
    setCurrentConversationId(conversationId);
    navigate(`/chat/${conversationId}`);
  };

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  return (
    <div className="app">
      <Sidebar
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        currentConversationId={currentConversationId}
        isOpen={isSidebarOpen}
      />
      <ChatInterface
        conversationId={currentConversationId}
        onConversationChange={handleConversationChange}
        onToggleSidebar={toggleSidebar}
        isSidebarOpen={isSidebarOpen}
      />
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/"
            element={
              <PrivateRoute>
                <MainLayout />
              </PrivateRoute>
            }
          />
          <Route
            path="/chat/:conversationId"
            element={
              <PrivateRoute>
                <MainLayout />
              </PrivateRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <PrivateRoute>
                <AdminLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="workers" element={<WorkerDashboard />} />
            <Route path="users" element={<Users />} />
            <Route path="settings" element={<Settings />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="integrations" element={<Integrations />} />
          </Route>
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
