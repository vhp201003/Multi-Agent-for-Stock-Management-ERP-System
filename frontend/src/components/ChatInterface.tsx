import React, { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { PieChart, Pie, Cell, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { apiService, generateId } from '../services/api';
import { wsService } from '../services/websocket';
import Toast, { type ToastMessage } from './Toast';
import ChatInput from './ChatInput';
import { processLayoutWithData } from '../utils/chartDataExtractor';
import { normalizeConversationMessages, normalizeLocalStorageMessages } from '../utils/messageNormalizer';
import { getConversation } from '../services/conversation';
import type { Message, LayoutField } from '../types/message';
import './ChatInterface.css';

// Extend Window interface for saveConversation
declare global {
  interface Window {
    saveConversation?: (id: string, title: string, lastMessage: string, messages: Message[]) => void;
  }
}

interface ChatInterfaceProps {
  conversationId: string;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ conversationId: propConversationId }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const answeredQueriesRef = React.useRef<Set<string>>(new Set());
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const saveTimeoutRef = React.useRef<NodeJS.Timeout | null>(null);

  // Toast notification helper
  const addToast = (message: string, type: 'success' | 'error' | 'warning' | 'info' = 'info', duration = 4000) => {
    const id = generateId();
    const newToast: ToastMessage = { id, message, type, duration };
    setToasts((prev) => [...prev, newToast]);

    if (duration) {
      setTimeout(() => removeToast(id), duration);
    }
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Auto-scroll to bottom when messages change
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load messages from localStorage when conversation changes
  useEffect(() => {
    const loadConversation = async () => {
      if (propConversationId) {
        setConversationId(propConversationId);
        
        try {
          const backendConversation = await getConversation(propConversationId, true);
          
          if (backendConversation && backendConversation.messages) {
            const normalizedMessages = normalizeConversationMessages(backendConversation.messages);
            setMessages(normalizedMessages);
            return;
          }
        } catch (error) {
          console.warn('[ChatInterface] Backend conversation not found, trying localStorage:', error);
        }
        
        const savedConversations = localStorage.getItem('conversations');
        if (savedConversations) {
          try {
            const conversations = JSON.parse(savedConversations);
            const conversation = conversations.find((c: { id: string }) => c.id === propConversationId);
            if (conversation && conversation.messages) {
              const normalizedMessages = normalizeLocalStorageMessages(conversation.messages);
              setMessages(normalizedMessages);
            }
          } catch (error) {
            console.error('[ChatInterface] Failed to load conversation from localStorage:', error);
            setMessages([]);
          }
        }
      } else {
        setConversationId(undefined);
        setMessages([]);
        answeredQueriesRef.current.clear();
      }
    };
    
    loadConversation();
  }, [propConversationId]);

  useEffect(() => {
    // Cleanup WebSocket khi component unmount
    return () => {
      wsService.disconnect();
      wsService.clearHandlers();
    };
  }, []);

  useEffect(() => {
    if (conversationId && messages.length > 0 && window.saveConversation) {
      // Debounce save to avoid excessive re-renders
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
      
      saveTimeoutRef.current = setTimeout(() => {
        const userMsg = messages.filter(m => m.type === 'user').pop();
        const assistantMsg = messages.filter(m => m.type === 'assistant').pop();
        
        window.saveConversation!(
          conversationId,
          userMsg?.content || 'New conversation',
          assistantMsg?.content || 'Response received',
          messages
        );
      }, 500); // Save after 500ms of inactivity
    }
  }, [messages, conversationId]);

  const handleSendMessage = useCallback(async (inputText: string) => {
    if (!inputText.trim() || loading) return;

    // Frontend tạo query_id
    const queryId = generateId();
    
    // Flag to prevent processing WebSocket updates after HTTP response
    let responseProcessed = false;
    
    // Nếu là message đầu tiên, conversation_id = query_id
    let currentConversationId = conversationId;
    if (!currentConversationId) {
      currentConversationId = queryId;
      setConversationId(currentConversationId);
    }

    const userMessage: Message = {
      id: queryId,
      type: 'user',
      content: inputText,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const queryText = inputText;
    setLoading(true);

    try {
      // BƯỚC 1: Kết nối WebSocket TRƯỚC để không bỏ lỡ updates
      wsService.connect(queryId);

      wsService.onMessage((update) => {
        // CRITICAL: Ignore updates after HTTP response processed
        if (responseProcessed) {
          console.log('Ignoring late WebSocket update after response processed');
          return;
        }
        
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
              isThinkingExpanded: true, // Start expanded during streaming
            };
            return [...prev, thinkingMsg];
          }
          
          // Add updates to thinking message
          return prev.map(msg => 
            msg.id === `${queryId}-thinking`
              ? { 
                  ...msg, 
                  updates: [...(msg.updates || []), update],
                  isThinkingExpanded: true, // Keep expanded while streaming
                }
              : msg
          );
        });
      });

      wsService.onClose(() => {
        // Only set loading false if response not yet processed
        if (!responseProcessed) {
          setLoading(false);
        }
      });

      wsService.onError((error) => {
        console.error('WebSocket error:', error);
        if (!responseProcessed) {
          setLoading(false);
        }
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
      // CRITICAL: Mark response as processed FIRST to prevent race conditions
      responseProcessed = true;
      
      // Then disconnect WebSocket to prevent duplicate thinking blocks
      wsService.disconnect();
      wsService.clearHandlers();
      
      setMessages((prevMessages) => {
        const thinkingMsg = prevMessages.find(msg => msg.id === `${queryId}-thinking`);
        const allUpdates = thinkingMsg?.updates || [];
        
        // Remove temporary thinking message
        const filtered = prevMessages.filter(msg => msg.id !== `${queryId}-thinking`);
        
        // Parse response for layout
        let layout: LayoutField[] | undefined;
        let fullData: unknown;
        let contentText = '';
        
        if (response) {
          if (typeof response === 'string') {
            contentText = response;
          } else if (typeof response === 'object') {
            // Extract final_response from HTTP response
            const finalResponse = (response as Record<string, any>).response?.final_response || (response as Record<string, any>).final_response;
            
            if (finalResponse?.layout) {
              // Extract layout and full_data
              layout = finalResponse.layout;
              fullData = finalResponse.full_data;
              
              // Process layout to fill chart data from full_data
              if (layout && fullData) {
                const processedLayout = processLayoutWithData(
                  layout as unknown as Record<string, unknown>[],
                  fullData
                );
                layout = processedLayout as unknown as LayoutField[];
              }
            } else {
              // Fallback to JSON string
              contentText = JSON.stringify(response, null, 2);
            }
          }
        }
        
        // Create messages to add
        const messagesToAdd = [];
        
        // Add thinking process if we have updates
        if (allUpdates.length > 0) {
          const displayThinkingMsg: Message = {
            id: `${queryId}-thinking-display`,
            type: 'system',
            content: '',
            timestamp: new Date(),
            updates: allUpdates,
            isThinkingExpanded: false, // Collapse after response complete
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
      
      // IMPORTANT: Set loading to false after processing response
      setLoading(false);

    } catch (error) {
      console.error('Failed to send message:', error);
      
      // CRITICAL: Mark as processed and disconnect to prevent duplicate blocks
      responseProcessed = true;
      wsService.disconnect();
      wsService.clearHandlers();
      
      setLoading(false);
      
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        type: 'system',
        content: 'Lỗi: Không thể gửi tin nhắn. Vui lòng thử lại.',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      addToast('Failed to send message. Please try again.', 'error');
    }
  }, [loading, conversationId]);

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
      
      default:
        return null;
    }
  };

  // Generic helper function to extract tool result summary
  const extractToolResultSummary = (toolResult: any, toolName: string): string => {
    // Handle string results
    if (typeof toolResult === 'string') {
      return toolResult;
    }

    // Handle object results - check for common summary patterns
    if (typeof toolResult === 'object' && toolResult !== null) {
      // Pattern 1: Check for 'summary' field (most tools follow this)
      if (toolResult.summary) {
        const summary = toolResult.summary;
        
        // Generic: count common fields
        const commonCountFields = [
          'total_items',
          'total_movements',
          'total_alerts',
          'total_value',
          'total_results',
          'count',
          'total'
        ];
        
        for (const field of commonCountFields) {
          if (field in summary && typeof summary[field] === 'number') {
            // Format the field name nicely
            const fieldLabel = field
              .replace(/total_/g, '')
              .replace(/_/g, ' ')
              .replace(/\b\w/g, l => l.toUpperCase());
            return `Found ${summary[field]} ${fieldLabel}`;
          }
        }

        // Pattern 2: Check for status-based summaries
        if (summary.out_of_stock !== undefined || summary.critical_stock !== undefined) {
          const alerts = [
            summary.out_of_stock && `${summary.out_of_stock} out of stock`,
            summary.critical_stock && `${summary.critical_stock} critical`,
            summary.low_stock && `${summary.low_stock} low stock`,
          ].filter(Boolean);
          if (alerts.length > 0) {
            return `Alerts: ${alerts.join(', ')}`;
          }
        }

        // Pattern 3: Generic summary fallback
        const summaryStr = JSON.stringify(summary).substring(0, 100);
        return summaryStr.length > 0 ? summaryStr : 'Operation successful';
      }

      // Pattern 4: Direct fields (no summary wrapper)
      const directCountFields = [
        'stock_level',
        'available_qty',
        'current_stock',
        'total_value',
        'items',
      ];
      
      for (const field of directCountFields) {
        if (field in toolResult) {
          const value = toolResult[field];
          if (typeof value === 'number') {
            const fieldLabel = field.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            return `${fieldLabel}: ${value}`;
          }
        }
      }

      // Pattern 5: Check for message field
      if (toolResult.message) {
        return toolResult.message;
      }

      // Pattern 6: Check for status field
      if (toolResult.status) {
        return `Status: ${toolResult.status}`;
      }
    }

    // Fallback
    return 'Success';
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
              <details className="thinking-process" open={message.isThinkingExpanded}>
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
                  
                  const isWorker = update.agent_type && !['orchestrator'].includes(update.agent_type);
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
                                        <strong>Result:</strong> {extractToolResultSummary(tool.tool_result, tool.tool_name)}
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
                            <details className="task-dependency-details">
                              <summary className="task-dependency-summary">
                                <strong>Tasks planned:</strong> {
                                  Object.values(update.result.task_dependency).flat().length
                                } task(s)
                                <span className="result-toggle">▼</span>
                              </summary>
                              <div className="task-dependency-full">
                                <pre>{JSON.stringify(update.result.task_dependency, null, 2)}</pre>
                              </div>
                            </details>
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
        <ChatInput onSendMessage={handleSendMessage} loading={loading} />
      </div>

      <Toast toasts={toasts} onRemove={removeToast} />
    </div>
  );
};

export default ChatInterface;
