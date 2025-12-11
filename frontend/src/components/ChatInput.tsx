import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import './ChatInput.css';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  loading: boolean;
}

const ChatInput: React.FC<ChatInputProps> = React.memo(({ onSendMessage, loading }) => {
  const [input, setInput] = useState('');
  const { hitlMode, toggleHitlMode } = useAuth();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [input, adjustHeight]);

  const handleSend = useCallback(() => {
    if (!input.trim() || loading) return;
    onSendMessage(input);
    setInput('');
    // Reset height manually after send is triggered (effect will also run but this ensures immediate reset)
    if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
    }
  }, [input, loading, onSendMessage]);

  const handleToggle = useCallback(() => {
    toggleHitlMode();
  }, [toggleHitlMode]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input-container">
      <div className="input-wrapper">
        <button
          className={`hitl-toggle ${hitlMode === 'auto' ? 'auto' : 'review'}`}
          onClick={handleToggle}
          title={hitlMode === 'review' ? 'Review Mode: Human approval required' : 'Auto Mode: Autonomous execution'}
          type="button"
        >
          {hitlMode === 'review' ? (
             <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
             </svg>
          ) : (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
            </svg>
          )}
        </button>
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask me anything..."
          disabled={loading}
          autoComplete="off"
          rows={1}
        />
        <button
          className="chat-send-button"
          onClick={handleSend}
          disabled={loading || !input.trim()}
          title="Send message"
          type="button"
        >
          {loading ? (
            <svg className="button-spinner" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                 <path d="M21 12a9 9 0 1 1-6.219-8.56"></path>
            </svg>
          ) : (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          )}
        </button>
      </div>
    </div>
  );
});

ChatInput.displayName = 'ChatInput';

export default ChatInput;
