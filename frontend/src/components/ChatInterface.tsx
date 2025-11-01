import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { PieChart, Pie, Cell, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { apiService, generateId, type TaskUpdate } from '../services/api';
import { wsService } from '../services/websocket';
import './ChatInterface.css';

// Extend Window interface for saveConversation
declare global {
  interface Window {
    saveConversation?: (id: string, title: string, lastMessage: string, messages: any[]) => void;
  }
}

interface LayoutField {
  field_type: string;
  title?: string;
  description?: string;
  content?: string;
  graph_type?: string;
  data?: {
    headers?: string[];
    rows?: any[][];
    labels?: string[];
    datasets?: Array<{
      label: string;
      data: any[];
    }>;
  };
}

interface Message {
  id: string;
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  updates?: TaskUpdate[];
  layout?: LayoutField[]; // Thêm layout cho structured response
}

interface ChatInterfaceProps {
  conversationId: string;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ conversationId: propConversationId }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const answeredQueriesRef = React.useRef<Set<string>>(new Set());
  const messagesEndRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load messages from localStorage when conversation changes
  useEffect(() => {
    if (propConversationId) {
      setConversationId(propConversationId);
      const savedConversations = localStorage.getItem('conversations');
      if (savedConversations) {
        try {
          const conversations = JSON.parse(savedConversations);
          const conversation = conversations.find((c: any) => c.id === propConversationId);
          if (conversation && conversation.messages) {
            // Convert timestamp strings back to Date objects
            const messages = conversation.messages.map((msg: any) => ({
              ...msg,
              timestamp: new Date(msg.timestamp)
            }));
            setMessages(messages);
          }
        } catch (error) {
          console.error('Failed to load conversation:', error);
          setMessages([]);
        }
      }
    } else {
      // New conversation
      setConversationId(undefined);
      setMessages([]);
      answeredQueriesRef.current.clear();
    }
  }, [propConversationId]);

  useEffect(() => {
    // Cleanup WebSocket khi component unmount
    return () => {
      wsService.disconnect();
      wsService.clearHandlers();
    };
  }, []);

  const handleSendMessage = async () => {
    if (!input.trim() || loading) return;

    // Frontend tạo query_id
    const queryId = generateId();
    
    // Nếu là message đầu tiên, conversation_id = query_id
    let currentConversationId = conversationId;
    if (!currentConversationId) {
      currentConversationId = queryId;
      setConversationId(currentConversationId);
    }

    const userMessage: Message = {
      id: queryId,
      type: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const queryText = input;
    setInput('');
    setLoading(true);

    try {
      // BƯỚC 1: Kết nối WebSocket TRƯỚC để không bỏ lỡ updates
      wsService.connect(queryId);

      wsService.onMessage((update) => {
        console.log('WebSocket update:', update);

        // Store all updates temporarily in thinking message
        setMessages((prev) => {
          const hasThinkingMsg = prev.some(msg => msg.id === `${queryId}-thinking`);
          if (!hasThinkingMsg) {
            const thinkingMsg: Message = {
              id: `${queryId}-thinking`,
              type: 'system',
              content: '',
              timestamp: new Date(),
              updates: [update],
            };
            return [...prev, thinkingMsg];
          }
          
          // Add updates to thinking message
          return prev.map(msg => 
            msg.id === `${queryId}-thinking`
              ? { ...msg, updates: [...(msg.updates || []), update] }
              : msg
          );
        });
      });

      wsService.onClose(() => {
        setLoading(false);
      });

      wsService.onError((error) => {
        console.error('WebSocket error:', error);
        setLoading(false);
      });

      // BƯỚC 2: Chờ 100ms để đảm bảo WebSocket đã connected
      await new Promise(resolve => setTimeout(resolve, 100));

      // BƯỚC 3: Gửi query và chờ HTTP response (final answer)
      const response = await apiService.submitQuery(
        queryId,
        queryText,
        currentConversationId
      );

      // BƯỚC 4: Process HTTP response - convert thinking message and add final answer
      setMessages((prevMessages) => {
        const thinkingMsg = prevMessages.find(msg => msg.id === `${queryId}-thinking`);
        const allUpdates = thinkingMsg?.updates || [];
        
        // Remove temporary thinking message
        let filtered = prevMessages.filter(msg => msg.id !== `${queryId}-thinking`);
        
        // Parse response for layout
        let layout: LayoutField[] | undefined;
        let contentText = '';
        
        if (response) {
          if (typeof response === 'string') {
            contentText = response;
          } else if (typeof response === 'object') {
            // Extract final_response from HTTP response
            const finalResponse = (response as any).response?.final_response || (response as any).final_response;
            
            if (finalResponse?.layout) {
              // Use layout from final_response
              layout = finalResponse.layout;
            } else {
              // Fallback to JSON string
              contentText = JSON.stringify(response, null, 2);
            }
          }
        }
        
        // Create messages to add
        let messagesToAdd = [];
        
        // Add thinking process if we have updates
        if (allUpdates.length > 0) {
          const displayThinkingMsg: Message = {
            id: `${queryId}-thinking-display`,
            type: 'system',
            content: '',
            timestamp: new Date(),
            updates: allUpdates,
          };
          messagesToAdd.push(displayThinkingMsg);
        }
        
        // Add assistant message with final answer
        if (contentText || layout) {
          const assistantMessage: Message = {
            id: `${queryId}-answer`,
            type: 'assistant',
            content: contentText,
            timestamp: new Date(),
            layout: layout,
          };
          messagesToAdd.push(assistantMessage);
        }
        
        return [...filtered, ...messagesToAdd];
      });
      
      // Save conversation to localStorage
      setTimeout(() => {
        if (window.saveConversation && currentConversationId) {
          setMessages((currentMessages) => {
            const userMsg = currentMessages.find(m => m.id === queryId);
            const assistantMsg = currentMessages.find(m => m.id === `${queryId}-answer`);
            window.saveConversation!(
              currentConversationId,
              userMsg?.content || queryText,
              assistantMsg?.content || 'Response received',
              currentMessages
            );
            return currentMessages;
          });
        }
      }, 0);

    } catch (error) {
      console.error('Failed to send message:', error);
      setLoading(false);
      
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        type: 'system',
        content: 'Lỗi: Không thể gửi tin nhắn. Vui lòng thử lại.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  // Render graph/chart
  const renderGraph = (field: LayoutField, index: number) => {
    if (!field.data || !field.data.labels || !field.data.datasets) {
      return null;
    }

    // Better color palette
    const COLORS = ['#667eea', '#764ba2', '#f093fb', '#4facfe', '#43e97b', '#fa709a', '#ffa502', '#26c485'];

    // Custom tooltip
    const CustomTooltip = ({ active, payload }: any) => {
      if (active && payload && payload.length) {
        return (
          <div className="chart-tooltip">
            <p className="tooltip-label">{payload[0].name || payload[0].payload.name}</p>
            <p className="tooltip-value">{payload[0].value || payload[0].payload.value}</p>
          </div>
        );
      }
      return null;
    };

    if (field.graph_type === 'piechart') {
      // Transform data for PieChart
      const pieData = field.data.labels.map((label, i) => ({
        name: label,
        value: Number(field.data?.datasets?.[0]?.data?.[i] || 0),
      }));

      return (
        <div key={index} className="layout-graph">
          {field.title && <h4>{field.title}</h4>}
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }: any) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((_entry, i) => (
                  <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.1)' }} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (field.graph_type === 'barchart') {
      // Transform data for BarChart
      const barData = field.data.labels.map((label, i) => {
        const dataPoint: any = { name: label };
        field.data?.datasets?.forEach((dataset) => {
          dataPoint[dataset.label] = Number(dataset.data[i] || 0);
        });
        return dataPoint;
      });

      return (
        <div key={index} className="layout-graph">
          {field.title && <h4>{field.title}</h4>}
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
              <XAxis dataKey="name" stroke="#666666" style={{ fontSize: '0.8rem' }} />
              <YAxis stroke="#666666" style={{ fontSize: '0.8rem' }} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }} />
              <Legend />
              {field.data?.datasets?.map((dataset, i) => (
                <Bar 
                  key={i} 
                  dataKey={dataset.label} 
                  fill={COLORS[i % COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (field.graph_type === 'linechart') {
      // Transform data for LineChart (for trends)
      const lineData = field.data.labels.map((label, i) => {
        const dataPoint: any = { name: label };
        field.data?.datasets?.forEach((dataset) => {
          dataPoint[dataset.label] = Number(dataset.data[i] || 0);
        });
        return dataPoint;
      });

      return (
        <div key={index} className="layout-graph">
          {field.title && <h4>{field.title}</h4>}
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={lineData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" />
              <XAxis dataKey="name" stroke="#666666" style={{ fontSize: '0.8rem' }} />
              <YAxis stroke="#666666" style={{ fontSize: '0.8rem' }} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }} />
              <Legend />
              {field.data?.datasets?.map((dataset, i) => (
                <Line 
                  key={i} 
                  type="monotone"
                  dataKey={dataset.label} 
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      );
    }

    return null;
  };

  // Render layout field
  const renderLayoutField = (field: LayoutField, index: number) => {
    switch (field.field_type) {
      case 'section_break':
        return (
          <div key={index} className="layout-section-break">
            {field.title && <h3>{field.title}</h3>}
            {field.description && <p>{field.description}</p>}
          </div>
        );
      
      case 'markdown':
        return (
          <div key={index} className="layout-markdown">
            <ReactMarkdown>{field.content || ''}</ReactMarkdown>
          </div>
        );
      
      case 'table':
        return (
          <div key={index} className="layout-table">
            {field.title && <h4>{field.title}</h4>}
            {field.data && field.data.headers && field.data.rows && (
              <table>
                <thead>
                  <tr>
                    {field.data.headers.map((header, i) => (
                      <th key={i}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {field.data.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>{String(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      
      case 'graph':
        return renderGraph(field, index);
      
      case 'column_break':
        return (
          <div key={index} className="layout-column-break" />
        );
      
      default:
        return null;
    }
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <h2>Multi-Agent Stock Management</h2>
        {conversationId && (
          <span className="conversation-id">
            Conversation: {conversationId.slice(0, 8)}
          </span>
        )}
      </div>

      <div className="chat-messages">
        {messages.map((message) => (
          <div key={message.id} className={`message message-${message.type}`}>
            <div className="message-content">
              {/* Hiển thị layout nếu có */}
              {message.layout && message.layout.length > 0 ? (
                <div className="structured-response">
                  {message.layout.map((field, index) => renderLayoutField(field, index))}
                </div>
              ) : (
                <div className="message-text">{message.content}</div>
              )}
              <div className="message-time">
                {message.timestamp.toLocaleTimeString()}
              </div>
            </div>

            {/* Hiển thị thinking process (task updates) - Collapsible */}
            {message.updates && message.updates.length > 0 && (
              <details className="thinking-process">
                <summary className="thinking-header">
                  <span className="thinking-title">Thinking Process</span>
                  <span className="thinking-count">{message.updates.length} steps</span>
                  <span className="thinking-toggle">›</span>
                </summary>
                <div className="thinking-content">
                {message.updates.map((update, index) => {
                  // Parse agent-specific information
                  const agentName = update.agent_type ? 
                    update.agent_type.charAt(0).toUpperCase() + update.agent_type.slice(1).replace('_', ' ') : 
                    'Agent';
                  
                  const isWorker = update.agent_type?.includes('inventory') || update.agent_type === 'worker';
                  const isOrchestrator = update.agent_type === 'orchestrator';
                  
                  return (
                    <div key={index} className={`thinking-step ${update.status}`}>
                      <div className="step-header">
                        <span className="step-agent">{agentName}</span>
                        {update.step && <span className="step-name">{update.step}</span>}
                        <span className={`step-status ${update.status}`}>
                          {update.status === 'done' && '✓'}
                          {update.status === 'processing' && '...'}
                          {update.status === 'failed' && '✗'}
                        </span>
                      </div>
                      
                      {update.message && (
                        <div className="step-message">
                          <strong>Action:</strong> {update.message}
                        </div>
                      )}
                      
                      {update.sub_query && (
                        <div className="step-query">
                          <strong>Query:</strong> {update.sub_query}
                        </div>
                      )}
                      
                      {/* Show tool results for worker agents */}
                      {update.result && isWorker && typeof update.result === 'object' && (
                        <div className="step-tools">
                          {update.result.tool_results && update.result.tool_results.length > 0 && (
                            <>
                              <strong>Tool Calls:</strong>
                              {update.result.tool_results.map((tool: any, toolIndex: number) => (
                                <div key={toolIndex} className="tool-call">
                                  <div className="tool-name">
                                    {tool.tool_name}
                                  </div>
                                  <div className="tool-params">
                                    <strong>Parameters:</strong>
                                    <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
                                  </div>
                                  {tool.tool_result && (
                                    <details className="tool-result-details">
                                      <summary className="tool-result-summary">
                                        <strong>Result:</strong> {
                                          typeof tool.tool_result === 'string' 
                                            ? tool.tool_result
                                            : tool.tool_result.summary?.total_movements 
                                              ? `Found ${tool.tool_result.summary.total_movements} movements`
                                              : tool.tool_result.message || 'Success'
                                        }
                                        <span className="result-toggle">▼</span>
                                      </summary>
                                      <div className="tool-result-full">
                                        <pre>{JSON.stringify(tool.tool_result, null, 2)}</pre>
                                      </div>
                                    </details>
                                  )}
                                </div>
                              ))}
                            </>
                          )}
                        </div>
                      )}
                      
                      {/* Show LLM reasoning for orchestrator */}
                      {update.result && isOrchestrator && typeof update.result === 'object' && (
                        <div className="step-reasoning">
                          {update.result.agents_needed && (
                            <div className="reasoning-item">
                              <strong>Agents needed:</strong> {update.result.agents_needed.join(', ')}
                            </div>
                          )}
                          {update.result.task_dependency && (
                            <div className="reasoning-item">
                              <strong>Tasks planned:</strong> {
                                Object.values(update.result.task_dependency).flat().length
                              } task(s)
                            </div>
                          )}
                        </div>
                      )}
                      
                      {update.llm_usage && (
                        <div className="step-tokens">
                          <span className="token-info">
                            💬 {update.llm_usage.total_tokens || 0} tokens
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })}
                </div>
              </details>
            )}
          </div>
        ))}
        {loading && (
          <div className="message message-system">
            <div className="message-content">
              <div className="loading-indicator">Processing...</div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-container">
        <div className="input-wrapper">
          <input
            type="text"
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
            placeholder="What's in your mind?..."
            disabled={loading}
          />
          <button
            className="chat-send-button"
            onClick={handleSendMessage}
            disabled={loading || !input.trim()}
          >
            <span>➤</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatInterface;
