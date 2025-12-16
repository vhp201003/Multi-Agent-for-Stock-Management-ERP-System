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
  isOpen?: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  isOpen = true,
}) => {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [useBackend] = useState(true); // Toggle backend vs localStorage
  const { user, logout, theme, toggleTheme } = useAuth();

  // Get user-specific localStorage key
  const getLocalStorageKey = () => {
    const userId = user?.id || "anonymous";
    return `conversations_${userId}`;
  };

  const loadFromLocalStorage = () => {
    try {
      const key = getLocalStorageKey();
      const stored = localStorage.getItem(key);
      if (stored) {
        const parsed = JSON.parse(stored);
        // Convert timestamp strings back to Date objects
        const conversations = parsed.map((conv: Conversation) => ({
          ...conv,
          timestamp: new Date(conv.timestamp),
        }));
        setConversations(conversations);
        console.log(
          `[Sidebar] Loaded ${conversations.length} conversations for user ${user?.id}`
        );
      } else {
        setConversations([]);
        console.log(`[Sidebar] No conversations found for user ${user?.id}`);
      }
    } catch (error) {
      console.error("Failed to load conversations from localStorage:", error);
      setConversations([]);
    }
  };

  const loadConversations = React.useCallback(async () => {
    console.log(
      "[Sidebar] Loading conversations, useBackend:",
      useBackend,
      "userId:",
      user?.id
    );
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
  }, [useBackend, user]);

  useEffect(() => {
    if (user) {
      // Migrate old conversations to user-specific key
      const oldKey = "conversations";
      const newKey = getLocalStorageKey();

      if (localStorage.getItem(oldKey) && !localStorage.getItem(newKey)) {
        console.log(
          `[Sidebar] Migrating conversations from '${oldKey}' to '${newKey}'`
        );
        const oldData = localStorage.getItem(oldKey);
        if (oldData) {
          localStorage.setItem(newKey, oldData);
          localStorage.removeItem(oldKey); // Clean up old data
          console.log("[Sidebar] Migration completed");
        }
      }

      loadConversations();
    } else {
      setConversations([]);
    }
  }, [loadConversations, user]);

  // Helper to save to localStorage with quota protection
  const saveToLocalStorage = (key: string, conversationsToSave: Conversation[]) => {
    try {
      // Create a lightweight version for localStorage
      // Strip 'messages' array to save space, keeping only metadata
      const lightweightData = conversationsToSave.map(conv => ({
        ...conv,
        messages: [] // Don't store full history in localStorage list to avoid QuotaExceededError
      }));
      
      localStorage.setItem(key, JSON.stringify(lightweightData));
    } catch (error) {
      if (error instanceof DOMException && error.name === 'QuotaExceededError') {
        console.error('[Sidebar] localStorage quota exceeded! Unable to save conversation list.');
        // Optional: Try to clear old items or warn user
      } else {
        console.error('[Sidebar] Failed to save to localStorage:', error);
      }
    }
  };

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
      const key = getLocalStorageKey();
      saveToLocalStorage(key, updated);
      console.log(`[Sidebar] Created new conversation for user ${user?.id}`);
    },
    [conversations, user]
  );

  // Update existing conversation (without moving to top)
  const updateConversation = React.useCallback(
    (id: string, title: string, lastMessage: string, messages: unknown[]) => {
      setConversations((prevConvs) => {
        const existingIndex = prevConvs.findIndex((c) => c.id === id);
        const key = getLocalStorageKey();

        let updated: Conversation[];
        if (existingIndex === -1) {
          // New conversation - add to top
          const newConv: Conversation = {
            id,
            title,
            lastMessage,
            timestamp: new Date(),
            messages,
          };
          updated = [newConv, ...prevConvs];
        } else {
          // Update existing - keep position
          updated = [...prevConvs];
          updated[existingIndex] = {
            ...updated[existingIndex],
            title,
            lastMessage,
            messages,
            // Don't update timestamp - keep original position
          };
        }
        
        saveToLocalStorage(key, updated);
        return updated;
      });
    },
    [user]
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
      console.log("[Sidebar] saveConversation called:", {
        id,
        messageCount: messages.length,
        moveToTop,
        userId: user?.id,
      });

      const conversation: Conversation = {
        id,
        title,
        lastMessage,
        timestamp: new Date(),
        messages,
      };

      setConversations((currentConversations) => {
        let updated: Conversation[];

        if (moveToTop) {
          // Move to top (for new messages)
          updated = [
            conversation,
            ...currentConversations.filter((c) => c.id !== id),
          ];
        } else {
          // Update in place (for final response or reload)
          const existingIndex = currentConversations.findIndex(
            (c) => c.id === id
          );
          if (existingIndex === -1) {
            updated = [conversation, ...currentConversations];
          } else {
            updated = [...currentConversations];
            updated[existingIndex] = {
              ...updated[existingIndex],
              title,
              lastMessage,
              messages,
              timestamp: updated[existingIndex].timestamp,
            };
          }
        }
        
        const key = getLocalStorageKey();
        saveToLocalStorage(key, updated);
        return updated;
      });
    },
    [user]
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
    const key = getLocalStorageKey();
    saveToLocalStorage(key, updated);
    console.log(`[Sidebar] Deleted conversation ${id} for user ${user?.id}`);

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
    <div className={`sidebar ${isOpen ? "open" : "closed"}`}>
      {/* Header with New Chat Button and Theme Toggle */}
      <div className="sidebar-header">
        <button
          className="new-chat-btn"
          onClick={onNewConversation}
          title="New chat"
        >
          New chat
        </button>
        <button
          className="theme-toggle-btn"
          onClick={toggleTheme}
          title={
            theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"
          }
        >
          {theme === "dark" ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="5"></circle>
              <line x1="12" y1="1" x2="12" y2="3"></line>
              <line x1="12" y1="21" x2="12" y2="23"></line>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
              <line x1="1" y1="12" x2="3" y2="12"></line>
              <line x1="21" y1="12" x2="23" y2="12"></line>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
          )}
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
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
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
