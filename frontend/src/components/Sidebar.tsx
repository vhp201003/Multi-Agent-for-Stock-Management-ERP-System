import React, { useState, useEffect } from 'react';
import './Sidebar.css';

interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messages?: any[]; // Store full conversation history
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
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    // Load conversations from localStorage
    loadConversations();
  }, []);

  const loadConversations = () => {
    try {
      const stored = localStorage.getItem('conversations');
      if (stored) {
        const parsed = JSON.parse(stored);
        // Convert timestamp strings back to Date objects
        const conversations = parsed.map((conv: any) => ({
          ...conv,
          timestamp: new Date(conv.timestamp),
        }));
        setConversations(conversations);
      }
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const saveConversation = (id: string, title: string, lastMessage: string, messages: any[]) => {
    const conversation: Conversation = {
      id,
      title,
      lastMessage,
      timestamp: new Date(),
      messages,
    };
    const updated = [conversation, ...conversations.filter(c => c.id !== id)];
    setConversations(updated);
    localStorage.setItem('conversations', JSON.stringify(updated));
  };

  const deleteConversation = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = conversations.filter(c => c.id !== id);
    setConversations(updated);
    localStorage.setItem('conversations', JSON.stringify(updated));
    
    if (currentConversationId === id) {
      onNewConversation();
    }
  };

  const filteredConversations = conversations.filter(conv => 
    (conv.title || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    (conv.lastMessage || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  const groupConversationsByDate = (convs: Conversation[]) => {
    const now = new Date();
    const today: Conversation[] = [];
    const yesterday: Conversation[] = [];
    const last7Days: Conversation[] = [];
    const older: Conversation[] = [];

    convs.forEach(conv => {
      const dateObj = conv.timestamp instanceof Date ? conv.timestamp : new Date(conv.timestamp);
      const diffDays = Math.floor((now.getTime() - dateObj.getTime()) / 86400000);

      if (diffDays === 0) today.push(conv);
      else if (diffDays === 1) yesterday.push(conv);
      else if (diffDays <= 7) last7Days.push(conv);
      else older.push(conv);
    });

    return { today, yesterday, last7Days, older };
  };



  // Expose saveConversation to parent via window
  useEffect(() => {
    window.saveConversation = saveConversation;
    return () => {
      delete window.saveConversation;
    };
  }, [conversations]);

  const { today, yesterday, last7Days, older } = groupConversationsByDate(filteredConversations);

  const renderConversationGroup = (title: string, convs: Conversation[]) => {
    if (convs.length === 0) return null;
    return (
      <div key={title} className="conversation-group">
        <div className="group-title">{title}</div>
        {convs.map((conv, index) => (
          <div
            key={`${title}-${conv.id}-${index}`}
            className={`conversation-item ${currentConversationId === conv.id ? 'active' : ''}`}
            onClick={() => onSelectConversation(conv.id)}
          >
            <div className="conversation-content">
              <h3 className="conversation-title">{conv.title}</h3>
              <p className="conversation-preview">{conv.lastMessage}</p>
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
      {/* Header with New Chat Button */}
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={onNewConversation} title="New chat">
          ✚ New chat
        </button>
      </div>

      <>
          {/* Search Bar */}
          <div className="sidebar-search">
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="search-input"
            />
          </div>

          {/* Your Conversations Header */}
          <div className="conversations-header">
          </div>

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
                {today.length > 0 && renderConversationGroup('Today', today)}
                {yesterday.length > 0 && renderConversationGroup('Yesterday', yesterday)}
                {last7Days.length > 0 && renderConversationGroup('Last 7 Days', last7Days)}
                {older.length > 0 && renderConversationGroup('Older', older)}
              </>
            )}
          </div>

          {/* Bottom Actions */}
          <div className="sidebar-footer">
            <button className="sidebar-footer-btn" title="Settings">
              Settings
            </button>
            <div className="user-profile">
              <div className="user-info">
                <div className="user-name">User</div>
              </div>
            </div>
          </div>
        </>
    </div>
  );
};

export default Sidebar;
