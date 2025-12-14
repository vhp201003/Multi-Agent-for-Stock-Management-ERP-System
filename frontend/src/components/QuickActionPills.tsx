import React from 'react';
import './QuickActionPills.css';

interface QuickActionPillsProps {
  suggestions: string[];
  onSelectSuggestion: (suggestion: string) => void;
  loading?: boolean;
}

const QuickActionPills: React.FC<QuickActionPillsProps> = ({
  suggestions,
  onSelectSuggestion,
  loading = false
}) => {
  if (!suggestions || suggestions.length === 0) {
    return null;
  }

  return (
    <div className="quick-action-pills">
      <div className="pills-container">
        {suggestions.map((suggestion, index) => (
          <button
            key={index}
            className="pill-button"
            onClick={() => onSelectSuggestion(suggestion)}
            disabled={loading}
            title={suggestion}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="9 12 11 14 15 10"></polyline>
            </svg>
            <span className="pill-text">{suggestion}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default QuickActionPills;
