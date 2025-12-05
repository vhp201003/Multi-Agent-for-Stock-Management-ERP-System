import React, { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { PieChart, Pie, Cell, BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { apiService, generateId } from '../services/api';
import { wsService } from '../services/websocket';
import { useAuth } from '../context/AuthContext';
import Toast, { type ToastMessage } from './Toast';
import ChatInput from './ChatInput';
import ApprovalCard from './ApprovalCard';
import { processLayoutWithData } from '../utils/chartDataExtractor';
import { normalizeConversationMessages, normalizeLocalStorageMessages } from '../utils/messageNormalizer';
import { getConversation } from '../services/conversation';
import type { Message, LayoutField, TaskUpdate } from '../types/message';
import type { ApprovalRequest, ApprovalResponse } from '../types/approval';
import type { WebSocketMessage } from '../services/websocket';
import './ChatInterface.css';

type QueueItem = 
  | { type: 'final_response'; response: any; queryId: string }
  | { type?: undefined; message: WebSocketMessage; queryId: string };

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
  // HITL: Track resolved approvals (approval_id -> action taken)
  const [resolvedApprovals, setResolvedApprovals] = useState<Map<string, ApprovalResponse['action']>>(new Map());
  const { hitlMode } = useAuth();
  const answeredQueriesRef = React.useRef<Set<string>>(new Set());
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const saveTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLoadDone = React.useRef(false);

  // Toast notification helper
  const addToast = useCallback((message: string, type: 'success' | 'error' | 'warning' | 'info' = 'info', duration = 4000) => {
    const id = generateId();
    const newToast: ToastMessage = { id, message, type, duration };
    setToasts((prev) => [...prev, newToast]);

    if (duration) {
      setTimeout(() => removeToast(id), duration);
    }
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // HITL: Handle approval response from inline card
  const handleApprovalResponse = useCallback((response: ApprovalResponse) => {
    // Mark as resolved
    setResolvedApprovals((prev) => {
      const newMap = new Map(prev);
      newMap.set(response.approval_id, response.action);
      return newMap;
    });

    // Send to backend via WebSocket
    wsService.sendApprovalResponse(response);

    // Show toast
    const actionText = response.action === 'approve' ? 'approved' : 
                       response.action === 'modify' ? 'modified & approved' : 'rejected';
    addToast(`Action ${actionText}`, response.action === 'reject' ? 'warning' : 'success');
  }, [addToast]);

  // Auto-scroll to bottom when messages change
  // Smart auto-scroll
  // Auto-scroll to bottom only on initial load or user message
  const scrollToBottom = useCallback(() => {
    // Always scroll on initial load
    if (!initialLoadDone.current && messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
      initialLoadDone.current = true;
      return;
    }

    const lastMessage = messages[messages.length - 1];
    const isUserMessage = lastMessage?.type === 'user';

    // Always scroll if the last message is from the user
    if (isUserMessage) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  useEffect(() => {
    scrollToBottom();
  }, [scrollToBottom]);

  // Load messages from backend or localStorage when conversation changes
  useEffect(() => {
    initialLoadDone.current = false;
    const loadConversation = async () => {
      if (propConversationId) {
        setConversationId(propConversationId);
        console.log('[ChatInterface] Loading conversation:', propConversationId);
        
        try {
          // ✅ Try backend first (persistent storage)
          console.log('[ChatInterface] Fetching from backend...');
          const backendConversation = await getConversation(propConversationId, true);
          
          if (backendConversation && backendConversation.messages && backendConversation.messages.length > 0) {
            console.log('[ChatInterface] Loaded from backend:', backendConversation.messages.length, 'messages');
            const normalizedMessages = normalizeConversationMessages(backendConversation.messages);
            setMessages(normalizedMessages);
            return;
          }
        } catch (error) {
          console.warn('[ChatInterface] Backend fetch failed:', error);
        }
        
        // ✅ Fallback to localStorage
        console.log('[ChatInterface] Trying localStorage...');
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

  const messageQueue = React.useRef<QueueItem[]>([]);
  const isProcessingQueue = React.useRef(false);

  const processQueue = useCallback(async () => {
    if (isProcessingQueue.current) return;
    isProcessingQueue.current = true;

    while (messageQueue.current.length > 0) {
      const item = messageQueue.current.shift();
      
      if (!item) continue;

      // Handle Final Response
      if (item.type === 'final_response') {
        const { response, queryId } = item;
        
        setMessages((prevMessages) => {
            const filtered = prevMessages.filter(msg => msg.id !== `${queryId}-thinking`);
            
            let layout: LayoutField[] | undefined;
            let fullData: unknown;
            let contentText = '';
            
            if (response) {
              if (typeof response === 'string') {
                contentText = response;
              } else if (typeof response === 'object') {
                const finalResponse = (response as Record<string, any>).response?.final_response || (response as Record<string, any>).final_response;
                
                if (finalResponse?.layout) {
                  layout = finalResponse.layout;
                  fullData = finalResponse.full_data;
                  if (layout && fullData) {
                    const processedLayout = processLayoutWithData(
                      layout as unknown as Record<string, unknown>[],
                      fullData
                    );
                    layout = processedLayout as unknown as LayoutField[];
                  }
                } else {
                  contentText = JSON.stringify(response, null, 2);
                }
              }
            }
            
            const messagesToAdd = [];
            // Find the thinking message to preserve its updates
            const thinkingMsg = prevMessages.find(msg => msg.id === `${queryId}-thinking`);
            if (thinkingMsg && thinkingMsg.updates && thinkingMsg.updates.length > 0) {
                 messagesToAdd.push({
                    ...thinkingMsg,
                    id: `${queryId}-thinking-display`,
                    isThinkingExpanded: false
                 });
            }

            if (contentText || layout) {
              messagesToAdd.push({
                id: `${queryId}-answer`,
                type: 'assistant',
                content: contentText,
                timestamp: new Date(),
                layout: layout,
              } as Message);
            }
            
            return [...filtered, ...messagesToAdd];
        });
        
        setLoading(false);
        continue;
      }

      // Handle WebSocket Message
      const { message, queryId } = item;
      
      // HITL: Handle approval messages - add as update in thinking process
      if (message.type === 'approval_required') {
        const approvalRequest = message.data as ApprovalRequest;
        
        // AUTO MODE: Automatically approve without user interaction
        if (hitlMode === 'auto') {
          const autoApprovalResponse: ApprovalResponse = {
            approval_id: approvalRequest.approval_id,
            query_id: approvalRequest.query_id,
            action: 'approve',
            modified_params: undefined
          };
          
          // Send auto-approval to backend
          wsService.sendApprovalResponse(autoApprovalResponse);
          
          // Mark as resolved immediately
          setResolvedApprovals((prev) => {
            const newMap = new Map(prev);
            newMap.set(approvalRequest.approval_id, 'approve');
            return newMap;
          });
          
          // Add auto-approved update to thinking process
          const autoApprovedUpdate: TaskUpdate = {
            type: 'approval_required',
            agent_type: approvalRequest.agent_type,
            status: 'auto_approved',
            approval: approvalRequest,
            timestamp: message.timestamp
          };
          
          setMessages((prev) => {
            const hasThinkingMsg = prev.some(msg => msg.id === `${queryId}-thinking`);
            if (!hasThinkingMsg) {
              return [...prev, {
                id: `${queryId}-thinking`,
                type: 'system',
                content: '',
                timestamp: new Date(),
                updates: [autoApprovedUpdate],
                isThinkingExpanded: true,
              }];
            }
            return prev.map(msg => 
              msg.id === `${queryId}-thinking`
                ? { ...msg, updates: [...(msg.updates || []), autoApprovedUpdate], isThinkingExpanded: true }
                : msg
            );
          });
          
          continue;
        }
        
        // REVIEW MODE: Show approval card for manual approval
        const approvalUpdate: TaskUpdate = {
          type: 'approval_required',
          agent_type: approvalRequest.agent_type,
          status: 'pending_approval',
          approval: approvalRequest,
          timestamp: message.timestamp
        };
        
        // Add to thinking message updates
        setMessages((prev) => {
          const hasThinkingMsg = prev.some(msg => msg.id === `${queryId}-thinking`);
          if (!hasThinkingMsg) {
            return [...prev, {
              id: `${queryId}-thinking`,
              type: 'system',
              content: '',
              timestamp: new Date(),
              updates: [approvalUpdate],
              isThinkingExpanded: true,
            }];
          }
          return prev.map(msg => 
            msg.id === `${queryId}-thinking`
              ? { ...msg, updates: [...(msg.updates || []), approvalUpdate], isThinkingExpanded: true }
              : msg
          );
        });
        
        // Scroll to show approval card
        setTimeout(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
        
        continue;
      }

      if (message.type === 'approval_resolved') {
        const { approval_id, action } = message.data;
        // Mark as resolved in state
        setResolvedApprovals((prev) => {
          const newMap = new Map(prev);
          newMap.set(approval_id, action);
          return newMap;
        });
        continue;
      }

      // Map message to UI update
      let uiUpdate: any = null;
      switch (message.type) {
          case 'orchestrator':
            uiUpdate = {
                ...message.data,
                agent_type: message.data.agent_type || 'orchestrator'
            };
            break;
          case 'tool_execution':
            uiUpdate = {
              agent_type: message.data.agent_type || 'worker',
              status: 'done',
              result: {
                tool_results: [{
                  tool_name: message.data.tool_name,
                  parameters: message.data.parameters,
                  tool_result: message.data.result
                }]
              },
              timestamp: message.timestamp
            };
            break;
          case 'thinking':
            // Check if this is orchestrator reasoning step (has step + explanation + conclusion)
            { const isOrchestratorReasoning = message.data.step !== undefined && message.data.explanation !== undefined && message.data.conclusion !== undefined;
            if (isOrchestratorReasoning) {
              uiUpdate = {
                agent_type: message.data.agent_type || 'orchestrator',
                type: 'reasoning_step',
                status: 'processing',
                step: message.data.step,
                explanation: message.data.explanation,
                conclusion: message.data.conclusion,
                timestamp: message.timestamp
              };
            } else {
              // Regular thinking message (worker agents)
              uiUpdate = {
                agent_type: message.data.agent_type || 'worker',
                status: 'processing',
                message: message.data.reasoning,
                timestamp: message.timestamp
              };
            }
            break; }
          case 'task_update':
            uiUpdate = message.data;
            break;
          case 'error':
             uiUpdate = {
              agent_type: message.data.agent_type || 'system',
              status: 'failed',
              message: message.data.error,
              timestamp: message.timestamp
            };
            break;
      }

      if (uiUpdate) {
        // Special handling for Typing Effect on 'thinking' messages
        if (message.type === 'thinking' && uiUpdate.message) {
            const fullText = uiUpdate.message;
            let currentText = '';
            const chunkSize = 15; // chars per tick
            
            // Create the update object initially with empty message
            const updateId = generateId();
            const initialUpdate = { ...uiUpdate, message: '', id: updateId };

            // Add the empty update first
            setMessages((prev) => {
                const hasThinkingMsg = prev.some(msg => msg.id === `${queryId}-thinking`);
                if (!hasThinkingMsg) {
                    return [...prev, {
                        id: `${queryId}-thinking`,
                        type: 'system',
                        content: '',
                        timestamp: new Date(),
                        updates: [initialUpdate],
                        isThinkingExpanded: true,
                    }];
                }
                return prev.map(msg => 
                    msg.id === `${queryId}-thinking`
                    ? { ...msg, updates: [...(msg.updates || []), initialUpdate], isThinkingExpanded: true }
                    : msg
                );
            });

            // Type out the text
            for (let i = 0; i < fullText.length; i += chunkSize) {
                currentText += fullText.slice(i, i + chunkSize);
                
                setMessages((prev) => prev.map(msg => {
                    if (msg.id !== `${queryId}-thinking`) return msg;
                    const updates = msg.updates || [];
                    const newUpdates = updates.map(u => 
                        (u as any).id === updateId ? { ...u, message: currentText } : u
                    );
                    return { ...msg, updates: newUpdates };
                }));
                
                await new Promise(r => setTimeout(r, 5)); // 10ms delay for typing speed
            }
        } else {
            // Non-typing updates (immediate)
            setMessages((prev) => {
              const hasThinkingMsg = prev.some(msg => msg.id === `${queryId}-thinking`);
              if (!hasThinkingMsg) {
                return [...prev, {
                  id: `${queryId}-thinking`,
                  type: 'system',
                  content: '',
                  timestamp: new Date(),
                  updates: [uiUpdate],
                  isThinkingExpanded: true,
                }];
              }
              return prev.map(msg => 
                msg.id === `${queryId}-thinking`
                  ? { ...msg, updates: [...(msg.updates || []), uiUpdate], isThinkingExpanded: true }
                  : msg
              );
            });
        }
        
        // Small delay between messages to prevent UI jitter
        await new Promise(r => setTimeout(r, 100));
      }
    }

    isProcessingQueue.current = false;
  }, [hitlMode]);

  const addToQueue = useCallback((item: any) => {
    messageQueue.current.push(item);
    processQueue();
  }, [processQueue]);

  const handleSendMessage = useCallback(async (inputText: string) => {
    if (!inputText.trim() || loading) return;

    const queryId = generateId();
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
      wsService.connect(queryId);

      wsService.onMessage((message) => {
        addToQueue({ message, queryId });
      });

      wsService.onClose(() => {
         // Optional: handle close
      });

      wsService.onError((error) => {
        console.error('WebSocket error:', error);
      });

      await new Promise(resolve => setTimeout(resolve, 100));

      const response = await apiService.submitQuery(
        queryId,
        queryText,
        currentConversationId
      );

      // Push final response to queue
      addToQueue({ type: 'final_response', response, queryId });

      wsService.disconnect();
      wsService.clearHandlers();

    } catch (error) {
      console.error('Failed to send message:', error);
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
  }, [loading, conversationId, addToQueue, addToast]);

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
  const extractToolResultSummary = (toolResult: any): string => {

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
              <details 
                className="thinking-process" 
                open={message.isThinkingExpanded}
                onClick={(e) => e.stopPropagation()}
              >
                <summary className="thinking-header" onClick={(e) => e.stopPropagation()}>
                  <span className="thinking-title">Thinking Process</span>
                  <span className="thinking-count">{message.updates.length} steps</span>
                  <span className="thinking-toggle">›</span>
                </summary>
                <div className="thinking-content">
                {message.updates.map((update, index) => {
                  // HITL: Render approval card inline
                  if ((update as any).type === 'approval_required' && (update as any).approval) {
                    const approval = (update as any).approval as ApprovalRequest;
                    const isResolved = resolvedApprovals.has(approval.approval_id);
                    const resolvedAction = resolvedApprovals.get(approval.approval_id);
                    
                    return (
                      <ApprovalCard
                        key={`approval-${approval.approval_id}`}
                        approval={approval}
                        onRespond={handleApprovalResponse}
                        isResolved={isResolved}
                        resolvedAction={resolvedAction}
                      />
                    );
                  }
                  
                  // Parse agent-specific information
                  const agentName = update.agent_type ? 
                    update.agent_type.charAt(0).toUpperCase() + update.agent_type.slice(1).replace('_', ' ') : 
                    'Agent';
                  
                  const isWorker = update.agent_type && !['orchestrator'].includes(update.agent_type);
                  const isOrchestrator = update.agent_type === 'orchestrator';
                  const isReasoningStep = (update as any).type === 'reasoning_step';
                  
                  // Reasoning step - render like normal step
                  if (isReasoningStep) {
                    return (
                      <div key={index} className="thinking-step processing">
                        <div className="step-header">
                          <span className="step-agent">{agentName}</span>
                          <span className="step-name">{update.step}</span>
                          <span className="step-status processing">...</span>
                        </div>
                        {(update as any).explanation && (
                          <div className="step-message">
                            {(update as any).explanation}
                          </div>
                        )}
                        {(update as any).conclusion && (
                          <div className="step-query">
                            → {(update as any).conclusion}
                          </div>
                        )}
                      </div>
                    );
                  }
                  
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
                          {update.message}
                        </div>
                      )}
                      
                      {update.sub_query && (
                        <div className="step-query">
                          {update.sub_query}
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
                                        <strong>Result:</strong> {extractToolResultSummary(tool.tool_result)}
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
