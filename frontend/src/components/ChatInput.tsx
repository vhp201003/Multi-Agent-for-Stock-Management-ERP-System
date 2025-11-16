import React, { useState, useCallback } from 'react';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  loading: boolean;
}

const ChatInput: React.FC<ChatInputProps> = React.memo(({ onSendMessage, loading }) => {
  const [input, setInput] = useState('');

  const handleSend = useCallback(() => {
    if (!input.trim() || loading) return;
    onSendMessage(input);
    setInput('');
  }, [input, loading, onSendMessage]);

  const handleKeyPress = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="chat-input-container">
      <div className="input-wrapper">
        <input
          type="text"
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="What's in your mind?..."
          disabled={loading}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck="false"
        />
        <button
          className="chat-send-button"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          {loading ? <span className="button-spinner">⟳</span> : <span>➤</span>}
        </button>
      </div>
    </div>
  );
});

ChatInput.displayName = 'ChatInput';

export default ChatInput;
