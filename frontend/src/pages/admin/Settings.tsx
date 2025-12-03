import React, { useState } from 'react';
import './AdminPages.css';

interface SettingSection {
  id: string;
  title: string;
  description: string;
}

const Settings: React.FC = () => {
  const [activeSection, setActiveSection] = useState('general');
  const [settings, setSettings] = useState({
    // General
    systemName: 'Multi-Agent ERP Assistant',
    welcomeMessage: 'Hello! How can I help you with inventory management today?',
    maxConversationHistory: 50,
    
    // Agent Settings
    hitlEnabled: true,
    hitlTimeout: 300,
    autoApproveThreshold: 0.9,
    
    // LLM Settings
    defaultModel: 'grok-3-mini',
    temperature: 0.7,
    maxTokens: 4096,
    
    // Notifications
    emailNotifications: true,
    slackIntegration: false,
    webhookUrl: '',
  });

  const sections: SettingSection[] = [
    { id: 'general', title: 'General', description: 'Basic system configuration' },
    { id: 'agents', title: 'Agent Settings', description: 'Configure agent behavior' },
    { id: 'llm', title: 'LLM Configuration', description: 'Language model settings' },
    { id: 'notifications', title: 'Notifications', description: 'Alert and notification settings' },
  ];

  const handleChange = (key: string, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    console.log('Saving settings:', settings);
    // TODO: Call API to save settings
    alert('Settings saved successfully!');
  };

  return (
    <div className="admin-page">
      <div className="page-header">
        <div>
          <h1>System Settings</h1>
          <p>Configure your multi-agent chatbot system</p>
        </div>
        <button className="primary-btn" onClick={handleSave}>💾 Save Changes</button>
      </div>

      <div className="settings-layout">
        {/* Settings Navigation */}
        <nav className="settings-nav">
          {sections.map((section) => (
            <div
              key={section.id}
              className={`settings-nav-item ${activeSection === section.id ? 'active' : ''}`}
              onClick={() => setActiveSection(section.id)}
            >
              <div className="nav-item-title">{section.title}</div>
              <div className="nav-item-desc">{section.description}</div>
            </div>
          ))}
        </nav>

        {/* Settings Content */}
        <div className="settings-content">
          {activeSection === 'general' && (
            <div className="settings-section">
              <h2>General Settings</h2>
              
              <div className="setting-group">
                <label className="setting-label">System Name</label>
                <input
                  type="text"
                  className="setting-input"
                  value={settings.systemName}
                  onChange={(e) => handleChange('systemName', e.target.value)}
                />
                <p className="setting-help">The name displayed in the chatbot header</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Welcome Message</label>
                <textarea
                  className="setting-textarea"
                  value={settings.welcomeMessage}
                  onChange={(e) => handleChange('welcomeMessage', e.target.value)}
                  rows={3}
                />
                <p className="setting-help">Initial message shown to users when starting a conversation</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Max Conversation History</label>
                <input
                  type="number"
                  className="setting-input small"
                  value={settings.maxConversationHistory}
                  onChange={(e) => handleChange('maxConversationHistory', parseInt(e.target.value))}
                  min={10}
                  max={200}
                />
                <p className="setting-help">Maximum number of messages to retain per conversation</p>
              </div>
            </div>
          )}

          {activeSection === 'agents' && (
            <div className="settings-section">
              <h2>Agent Settings</h2>
              
              <div className="setting-group">
                <label className="setting-label">Human-in-the-Loop (HITL)</label>
                <div className="setting-toggle">
                  <input
                    type="checkbox"
                    id="hitl-toggle"
                    checked={settings.hitlEnabled}
                    onChange={(e) => handleChange('hitlEnabled', e.target.checked)}
                  />
                  <label htmlFor="hitl-toggle" className="toggle-label">
                    {settings.hitlEnabled ? 'Enabled' : 'Disabled'}
                  </label>
                </div>
                <p className="setting-help">Require human approval for critical actions like orders</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">HITL Timeout (seconds)</label>
                <input
                  type="number"
                  className="setting-input small"
                  value={settings.hitlTimeout}
                  onChange={(e) => handleChange('hitlTimeout', parseInt(e.target.value))}
                  min={60}
                  max={3600}
                  disabled={!settings.hitlEnabled}
                />
                <p className="setting-help">Time to wait for human approval before timeout</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Auto-approve Confidence Threshold</label>
                <div className="slider-group">
                  <input
                    type="range"
                    className="setting-slider"
                    min="0"
                    max="1"
                    step="0.05"
                    value={settings.autoApproveThreshold}
                    onChange={(e) => handleChange('autoApproveThreshold', parseFloat(e.target.value))}
                    disabled={!settings.hitlEnabled}
                  />
                  <span className="slider-value">{(settings.autoApproveThreshold * 100).toFixed(0)}%</span>
                </div>
                <p className="setting-help">Actions with confidence above this threshold may be auto-approved</p>
              </div>

              <div className="agent-list-config">
                <h3>Active Agents</h3>
                <div className="agent-toggle-list">
                  {['orchestrator', 'inventory_agent', 'analytics_agent', 'forecasting_agent', 'ordering_agent', 'summary_agent', 'chat_agent'].map(agent => (
                    <div key={agent} className="agent-toggle-item">
                      <input type="checkbox" id={agent} defaultChecked />
                      <label htmlFor={agent}>{agent.replace('_agent', '').replace('_', ' ')}</label>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeSection === 'llm' && (
            <div className="settings-section">
              <h2>LLM Configuration</h2>
              
              <div className="setting-group">
                <label className="setting-label">Default Model</label>
                <select
                  className="setting-select"
                  value={settings.defaultModel}
                  onChange={(e) => handleChange('defaultModel', e.target.value)}
                >
                  <option value="grok-3-mini">Grok 3 Mini (Fast)</option>
                  <option value="grok-3">Grok 3 (Balanced)</option>
                  <option value="grok-3-reasoning">Grok 3 Reasoning (Advanced)</option>
                  <option value="deepseek-r1">DeepSeek R1</option>
                </select>
                <p className="setting-help">Primary LLM used for agent responses</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Temperature</label>
                <div className="slider-group">
                  <input
                    type="range"
                    className="setting-slider"
                    min="0"
                    max="1"
                    step="0.1"
                    value={settings.temperature}
                    onChange={(e) => handleChange('temperature', parseFloat(e.target.value))}
                  />
                  <span className="slider-value">{settings.temperature}</span>
                </div>
                <p className="setting-help">Higher values = more creative, lower = more deterministic</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Max Tokens</label>
                <input
                  type="number"
                  className="setting-input small"
                  value={settings.maxTokens}
                  onChange={(e) => handleChange('maxTokens', parseInt(e.target.value))}
                  min={256}
                  max={32768}
                  step={256}
                />
                <p className="setting-help">Maximum tokens per response</p>
              </div>
            </div>
          )}

          {activeSection === 'notifications' && (
            <div className="settings-section">
              <h2>Notification Settings</h2>
              
              <div className="setting-group">
                <label className="setting-label">Email Notifications</label>
                <div className="setting-toggle">
                  <input
                    type="checkbox"
                    id="email-toggle"
                    checked={settings.emailNotifications}
                    onChange={(e) => handleChange('emailNotifications', e.target.checked)}
                  />
                  <label htmlFor="email-toggle" className="toggle-label">
                    {settings.emailNotifications ? 'Enabled' : 'Disabled'}
                  </label>
                </div>
                <p className="setting-help">Receive email alerts for critical events</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Slack Integration</label>
                <div className="setting-toggle">
                  <input
                    type="checkbox"
                    id="slack-toggle"
                    checked={settings.slackIntegration}
                    onChange={(e) => handleChange('slackIntegration', e.target.checked)}
                  />
                  <label htmlFor="slack-toggle" className="toggle-label">
                    {settings.slackIntegration ? 'Connected' : 'Not Connected'}
                  </label>
                </div>
                <p className="setting-help">Send notifications to a Slack channel</p>
              </div>

              <div className="setting-group">
                <label className="setting-label">Webhook URL</label>
                <input
                  type="url"
                  className="setting-input"
                  value={settings.webhookUrl}
                  onChange={(e) => handleChange('webhookUrl', e.target.value)}
                  placeholder="https://your-webhook-url.com/notify"
                />
                <p className="setting-help">Custom webhook for external integrations</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Settings;
