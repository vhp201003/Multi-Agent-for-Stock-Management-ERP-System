import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  listConversations,
  deleteConversation as deleteConversationAPI,
} from "../services/conversation";
import { useAuth } from "../context/AuthContext";
import "./Sidebar.css";

interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messages?: unknown[]; // Store full conversation history
}

interface SidebarProps {
  currentConversationId?: string;
  onSelectConversation: (conversationId: string) => void;
  onNewConversation: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}) => {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [useBackend] = useState(true); // Toggle backend vs localStorage
  const { user, logout, theme, toggleTheme } = useAuth();

  const loadFromLocalStorage = () => {
    try {
      const stored = localStorage.getItem("conversations");
      if (stored) {
        const parsed = JSON.parse(stored);
        // Convert timestamp strings back to Date objects
        const conversations = parsed.map((conv: Conversation) => ({
          ...conv,
          timestamp: new Date(conv.timestamp),
        }));
        setConversations(conversations);
      }
    } catch (error) {
      console.error("Failed to load conversations from localStorage:", error);
    }
  };

  const loadConversations = React.useCallback(async () => {
    console.log("[Sidebar] Loading conversations, useBackend:", useBackend);
    if (useBackend) {
      try {
        console.log("[Sidebar] Fetching from backend...");
        const response = await listConversations(100, 0);
        console.log("[Sidebar] Backend response:", response);

        if (
          response &&
          response.conversations &&
          response.conversations.length > 0
        ) {
          const backendConversations = response.conversations.map((conv) => ({
            id: conv.id,
            title: conv.title || `Conversation ${conv.id.slice(0, 8)}`,
            lastMessage: `${conv.message_count || 0} messages`,
            timestamp: new Date(conv.updated_at),
            messages: conv.messages || [],
          }));
          console.log(
            "[Sidebar] Loaded",
            backendConversations.length,
            "conversations from backend"
          );
          setConversations(backendConversations);
          return;
        }
      } catch (error) {
        console.warn("[Sidebar] Failed to load from backend:", error);
        // Continue to fallback
      }
    }

    // ✅ Fallback to localStorage
    console.log("[Sidebar] Falling back to localStorage");
    loadFromLocalStorage();
  }, [useBackend]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Create a new conversation entry (for new chat)
  const createNewConversation = React.useCallback(
    (id: string, title: string = "New conversation") => {
      const conversation: Conversation = {
        id,
        title,
        lastMessage: "Start chatting...",
        timestamp: new Date(),
        messages: [],
      };
      const updated = [
        conversation,
        ...conversations.filter((c) => c.id !== id),
      ];
      setConversations(updated);
      localStorage.setItem("conversations", JSON.stringify(updated));
    },
    [conversations]
  );

  // Update existing conversation (without moving to top)
  const updateConversation = React.useCallback(
    (id: string, title: string, lastMessage: string, messages: unknown[]) => {
      setConversations((prevConvs) => {
        const existingIndex = prevConvs.findIndex((c) => c.id === id);
        if (existingIndex === -1) {
          // New conversation - add to top
          const newConv: Conversation = {
            id,
            title,
            lastMessage,
            timestamp: new Date(),
            messages,
          };
          const updated = [newConv, ...prevConvs];
          localStorage.setItem("conversations", JSON.stringify(updated));
          return updated;
        } else {
          // Update existing - keep position
          const updated = [...prevConvs];
          updated[existingIndex] = {
            ...updated[existingIndex],
            title,
            lastMessage,
            messages,
            // Don't update timestamp - keep original position
          };
          localStorage.setItem("conversations", JSON.stringify(updated));
          return updated;
        }
      });
    },
    []
  );

  // Move conversation to top when new message is sent
  const saveConversation = React.useCallback(
    (
      id: string,
      title: string,
      lastMessage: string,
      messages: unknown[],
      moveToTop: boolean = true
    ) => {
      const conversation: Conversation = {
        id,
        title,
        lastMessage,
        timestamp: new Date(),
        messages,
      };

      if (moveToTop) {
        // Move to top (for new messages)
        const updated = [
          conversation,
          ...conversations.filter((c) => c.id !== id),
        ];
        setConversations(updated);
        localStorage.setItem("conversations", JSON.stringify(updated));
      } else {
        // Update in place (for selecting existing conversation)
        updateConversation(id, title, lastMessage, messages);
      }
    },
    [conversations, updateConversation]
  );

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();

    if (useBackend) {
      try {
        await deleteConversationAPI(id);
      } catch (error) {
        console.error("Failed to delete from backend:", error);
      }
    }

    const updated = conversations.filter((c) => c.id !== id);
    setConversations(updated);
    localStorage.setItem("conversations", JSON.stringify(updated));

    if (currentConversationId === id) {
      onNewConversation();
    }
  };

  const filteredConversations = conversations.filter(
    (conv) =>
      (conv.title || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (conv.lastMessage || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const groupConversationsByDate = (convs: Conversation[]) => {
    const now = new Date();
    const today: Conversation[] = [];
    const yesterday: Conversation[] = [];
    const last7Days: Conversation[] = [];
    const older: Conversation[] = [];

    convs.forEach((conv) => {
      const dateObj =
        conv.timestamp instanceof Date
          ? conv.timestamp
          : new Date(conv.timestamp);
      const diffDays = Math.floor(
        (now.getTime() - dateObj.getTime()) / 86400000
      );

      if (diffDays === 0) today.push(conv);
      else if (diffDays === 1) yesterday.push(conv);
      else if (diffDays <= 7) last7Days.push(conv);
      else older.push(conv);
    });

    return { today, yesterday, last7Days, older };
  };

  // Expose functions to parent via window
  useEffect(() => {
    window.saveConversation = saveConversation;
    window.createNewConversation = createNewConversation;
    window.updateConversation = updateConversation;
    return () => {
      delete window.saveConversation;
      delete window.createNewConversation;
      delete window.updateConversation;
    };
  }, [saveConversation, createNewConversation, updateConversation]);

  const { today, yesterday, last7Days, older } = groupConversationsByDate(
    filteredConversations
  );

  // Helper function to clean up preview text
  const getCleanPreview = (lastMessage: string): string => {
    // If it starts with {"layout" or similar JSON, hide it
    if (
      lastMessage.startsWith('{"layout') ||
      lastMessage.startsWith('[{"field')
    ) {
      return "Response received";
    }
    // If it's a message count, keep it
    if (lastMessage.includes("messages")) {
      return lastMessage;
    }
    // Otherwise truncate to reasonable length
    return lastMessage.length > 60
      ? lastMessage.slice(0, 60) + "..."
      : lastMessage;
  };

  const renderConversationGroup = (title: string, convs: Conversation[]) => {
    if (convs.length === 0) return null;
    return (
      <div key={title} className="conversation-group">
        <div className="group-title">{title}</div>
        {convs.map((conv, index) => (
          <div
            key={`${title}-${conv.id}-${index}`}
            className={`conversation-item ${
              currentConversationId === conv.id ? "active" : ""
            }`}
            onClick={() => onSelectConversation(conv.id)}
          >
            <div className="conversation-content">
              <h3 className="conversation-title">{conv.title}</h3>
              <p className="conversation-preview">
                {getCleanPreview(conv.lastMessage)}
              </p>
            </div>
            <button
              className="delete-btn"
              onClick={(e) => deleteConversation(conv.id, e)}
              title="Delete conversation"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="sidebar">
      {/* Header with New Chat Button and Theme Toggle */}
      <div className="sidebar-header">
        <button
          className="new-chat-btn"
          onClick={onNewConversation}
          title="New chat"
        >
          ✚ New chat
        </button>
        <button
          className="theme-toggle-btn"
          onClick={toggleTheme}
          title={
            theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"
          }
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
      </div>

      <>
        {/* Search Bar */}
        <div className="sidebar-search">
          <div className="search-input-wrapper">
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="search-input"
            />
            {searchQuery && (
              <button
                className="clear-search-btn"
                onClick={() => setSearchQuery("")}
                title="Clear search"
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Your Conversations Header */}
        <div className="conversations-header"></div>

        {/* Conversations List */}
        <div className="conversations-list">
          {conversations.length === 0 ? (
            <div className="empty-state">
              <p>No conversations yet</p>
              <p className="empty-hint">Start a new chat to begin</p>
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="empty-state">
              <p>No results found</p>
              <p className="empty-hint">Try a different search term</p>
            </div>
          ) : (
            <>
              {today.length > 0 && renderConversationGroup("Today", today)}
              {yesterday.length > 0 &&
                renderConversationGroup("Yesterday", yesterday)}
              {last7Days.length > 0 &&
                renderConversationGroup("Last 7 Days", last7Days)}
              {older.length > 0 && renderConversationGroup("Older", older)}
            </>
          )}
        </div>

        {/* Bottom Actions */}
        <div className="sidebar-footer">
          <div className="user-profile">
            <div className="user-avatar">
              {user?.email?.charAt(0).toUpperCase() || "U"}
            </div>
            <div className="user-info">
              <div className="user-name">
                {user?.full_name || user?.email || "User"}
              </div>
              {user?.email && <div className="user-email">{user.email}</div>}
            </div>
            <button
              className="admin-btn"
              onClick={() => navigate("/admin")}
              title="Admin Dashboard"
              style={{
                background: "none",
                border: "none",
                color: "var(--text-secondary)",
                cursor: "pointer",
                marginRight: "8px",
              }}
            >
              ⚙️
            </button>
            <button className="logout-btn" onClick={logout} title="Logout">
              ⎋
            </button>
          </div>
        </div>
      </>
    </div>
  );
};

export default Sidebar;
