import React, { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  ZAxis,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { apiService, generateId } from "../services/api";
import { wsService } from "../services/websocket";
import { useAuth } from "../context/AuthContext";
import Toast, { type ToastMessage } from "./Toast";
import ChatInput from "./ChatInput";
import ApprovalCard from "./ApprovalCard";
import QuickActionPills from "./QuickActionPills";
import { processLayoutWithData } from "../utils/chartDataExtractor";
import {
  normalizeConversationMessages,
  normalizeLocalStorageMessages,
} from "../utils/messageNormalizer";
import { getConversation, getQuickActions } from "../services/conversation";
import type { Message, LayoutField, TaskUpdate } from "../types/message";
import type { ApprovalRequest, ApprovalResponse } from "../types/approval";
import type { WebSocketMessage } from "../services/websocket";
import "./ChatInterface.css";

type QueueItem =
  | {
      type: "final_response";
      response: any;
      queryId: string;
      isNewConversation?: boolean;
      conversationId?: string;
    }
  | { type?: undefined; message: WebSocketMessage; queryId: string };

// Extend Window interface for saveConversation
declare global {
  interface Window {
    saveConversation?: (
      id: string,
      title: string,
      lastMessage: string,
      messages: Message[],
      moveToTop?: boolean
    ) => void;
    createNewConversation?: (id: string, title?: string) => void;
    updateConversation?: (
      id: string,
      title: string,
      lastMessage: string,
      messages: Message[]
    ) => void;
  }
}


const PaginatedTable: React.FC<{ headers: string[]; rows: any[][]; totalItems?: number }> = ({
  headers,
  rows,
  totalItems,
}) => {
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;

  const totalPages = Math.ceil(rows.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = Math.min(startIndex + itemsPerPage, rows.length);
  const currentRows = rows.slice(startIndex, endIndex);

  // Generate page numbers to display
  const getPageNumbers = () => {
    const pages: (number | string)[] = [];
    const maxVisible = 5;
    
    if (totalPages <= maxVisible + 2) {
      // Show all pages
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      // Show first, last, and pages around current
      pages.push(1);
      
      if (currentPage > 3) pages.push('...');
      
      const start = Math.max(2, currentPage - 1);
      const end = Math.min(totalPages - 1, currentPage + 1);
      
      for (let i = start; i <= end; i++) pages.push(i);
      
      if (currentPage < totalPages - 2) pages.push('...');
      
      pages.push(totalPages);
    }
    return pages;
  };

  if (rows.length === 0) return null;

  const displayTotalItems = totalItems || rows.length;

  return (
    <div className="paginated-table-container">
      <table>
        <thead>
          <tr>
            {headers.map((header, i) => (
              <th key={i}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {currentRows.map((row, rowIndex) => (
            <tr key={startIndex + rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{
                    typeof cell === 'object' && cell !== null 
                    ? JSON.stringify(cell) 
                    : String(cell)
                }</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      
      {/* Always show pagination footer */}
      <div className="pagination-controls">
        {/* Previous Button */}
        <button
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={currentPage === 1}
          className="pagination-btn"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
          Trước
        </button>

        {/* Page Numbers */}
        {totalPages > 1 && (
          <div className="pagination-pages">
            {getPageNumbers().map((page, idx) => (
              typeof page === 'number' ? (
                <button
                  key={idx}
                  onClick={() => setCurrentPage(page)}
                  className={`pagination-page-btn ${currentPage === page ? 'active' : ''}`}
                >
                  {page}
                </button>
              ) : (
                <span key={idx} className="pagination-ellipsis">...</span>
              )
            ))}
          </div>
        )}

        {/* Next Button */}
        <button
          onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
          disabled={currentPage === totalPages || totalPages === 1}
          className="pagination-btn"
        >
          Sau
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </button>

        {/* Info */}
        <div className="pagination-info">
          <span>Hiển thị <strong>{startIndex + 1}-{endIndex}</strong> / <strong>{displayTotalItems}</strong> mục</span>
        </div>
      </div>
    </div>
  );
};

interface ChatInterfaceProps {
  conversationId: string;
  onConversationChange?: (conversationId: string) => void;
  onToggleSidebar?: () => void;
  isSidebarOpen?: boolean;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  conversationId: propConversationId,
  onConversationChange,
  onToggleSidebar,
  isSidebarOpen = true,
}) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [quickActions, setQuickActions] = useState<string[]>([]);
  // HITL: Track resolved approvals (approval_id -> action taken)
  const [resolvedApprovals, setResolvedApprovals] = useState<
    Map<string, ApprovalResponse["action"]>
  >(new Map());
  const { hitlMode, useCache } = useAuth();
  const answeredQueriesRef = React.useRef<Set<string>>(new Set());
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const chatMessagesRef = React.useRef<HTMLDivElement>(null);
  const saveTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const initialLoadDone = React.useRef(false);
  const isLoadingConversation = React.useRef(false);
  const skipLoadForNewConversation = React.useRef<string | null>(null);
  const [showInfoModal, setShowInfoModal] = useState(false);
  


  // Toast notification helper
  const addToast = useCallback(
    (
      message: string,
      type: "success" | "error" | "warning" | "info" = "info",
      duration = 4000
    ) => {
      const id = generateId();
      const newToast: ToastMessage = { id, message, type, duration };
      setToasts((prev) => [...prev, newToast]);

      if (duration) {
        setTimeout(() => removeToast(id), duration);
      }
    },
    []
  );

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Fetch quick actions for the current conversation
  const fetchQuickActions = useCallback(async (convId: string) => {
    try {
      const response = await getQuickActions(convId);
      if (response && response.suggestions && response.suggestions.length > 0) {
        setQuickActions(response.suggestions);
      } else {
        setQuickActions([]);
      }
    } catch (error) {
      console.error("[ChatInterface] Failed to fetch quick actions:", error);
      setQuickActions([]);
    }
  }, []);

  // HITL: Handle approval response from inline card
  const handleApprovalResponse = useCallback(
    async (response: ApprovalResponse) => {
      console.log("[ChatInterface] 🔔 Handling approval response:", {
        approval_id: response.approval_id,
        action: response.action,
        query_id: response.query_id,
      });

      // Mark as resolved immediately for UI feedback
      setResolvedApprovals((prev) => {
        const newMap = new Map(prev);
        newMap.set(response.approval_id, response.action);
        return newMap;
      });

      try {
        // Send approval response via REST API (more reliable than WebSocket)
        await apiService.submitApprovalResponse(response);
        console.log(
          "[ChatInterface] ✅ Approval response sent successfully via REST API"
        );

        // Show success toast
        const actionText =
          response.action === "approve"
            ? "approved"
            : response.action === "modify"
            ? "modified & approved"
            : "rejected";
        addToast(`Action ${actionText}`, "success");
      } catch (error) {
        console.error(
          "[ChatInterface] ❌ Failed to send approval response:",
          error
        );
        addToast(
          "Failed to send approval response. Please try again.",
          "error"
        );

        // Revert resolved state on error
        setResolvedApprovals((prev) => {
          const newMap = new Map(prev);
          newMap.delete(response.approval_id);
          return newMap;
        });
      }
    },
    [addToast]
  );

  // Auto-scroll to bottom when messages change
  const scrollToBottom = useCallback(() => {
    const container = chatMessagesRef.current;

    // Always scroll on initial load
    if (!initialLoadDone.current && messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
      initialLoadDone.current = true;
      return;
    }

    const lastMessage = messages[messages.length - 1];
    const isUserMessage = lastMessage?.type === "user";

    // Only auto-scroll if user near bottom to avoid fighting manual scroll
    let isNearBottom = true;
    if (container) {
      const distanceToBottom =
        container.scrollHeight - container.clientHeight - container.scrollTop;
      isNearBottom = distanceToBottom < 200;
    }

    // Always scroll if the last message is from the user
    if (isUserMessage) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
      return;
    }

    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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
        // Skip loading if this is a newly created conversation
        if (skipLoadForNewConversation.current === propConversationId) {
          console.log(
            "[ChatInterface] Skipping load for newly created conversation:",
            propConversationId
          );
          setConversationId(propConversationId);
          setQuickActions([]);
          skipLoadForNewConversation.current = null;
          isLoadingConversation.current = false;
          return;
        }

        isLoadingConversation.current = true; // Set flag when loading
        setConversationId(propConversationId);
        setQuickActions([]);
        console.log(
          "[ChatInterface] Loading conversation:",
          propConversationId
        );

        try {
          // ✅ Try backend first (persistent storage)
          console.log("[ChatInterface] Fetching from backend...");
          const backendConversation = await getConversation(
            propConversationId,
            true
          );

          if (
            backendConversation &&
            backendConversation.messages &&
            backendConversation.messages.length > 0
          ) {
            console.log(
              "[ChatInterface] Loaded from backend:",
              backendConversation.messages.length,
              "messages"
            );
            const normalizedMessages = normalizeConversationMessages(
              backendConversation.messages
            );
            setMessages(normalizedMessages);
            // Fetch quick actions for this conversation
            fetchQuickActions(propConversationId);
            // Clear flag after a short delay to allow messages to settle
            setTimeout(() => {
              isLoadingConversation.current = false;
            }, 1000);
            return;
          }
        } catch (error) {
          console.warn("[ChatInterface] Backend fetch failed:", error);
        }

        // ✅ Fallback to localStorage
        console.log("[ChatInterface] Trying localStorage...");
        const savedConversations = localStorage.getItem("conversations");
        if (savedConversations) {
          try {
            const conversations = JSON.parse(savedConversations);
            const conversation = conversations.find(
              (c: { id: string }) => c.id === propConversationId
            );
            console.log(
              "[ChatInterface] Found conversation in localStorage:",
              !!conversation,
              "messages:",
              conversation?.messages?.length
            );
            if (conversation && conversation.messages) {
              const normalizedMessages = normalizeLocalStorageMessages(
                conversation.messages
              );
              console.log(
                "[ChatInterface] Normalized messages:",
                normalizedMessages.length
              );
              setMessages(normalizedMessages);
              // Fetch quick actions for this conversation
              fetchQuickActions(propConversationId);
              // Clear flag after a short delay
              setTimeout(() => {
                isLoadingConversation.current = false;
              }, 1000);
            } else {
              console.warn(
                "[ChatInterface] Conversation found but no messages!"
              );
              isLoadingConversation.current = false;
            }
          } catch (error) {
            console.error(
              "[ChatInterface] Failed to load conversation from localStorage:",
              error
            );
            setMessages([]);
            isLoadingConversation.current = false;
          }
        } else {
          isLoadingConversation.current = false;
        }
      } else {
        setConversationId(undefined);
        setMessages([]);
        setQuickActions([]); // Clear quick actions when no conversation
        answeredQueriesRef.current.clear();
        isLoadingConversation.current = false;
      }
    };

    loadConversation();
  }, [propConversationId, fetchQuickActions]);

  useEffect(() => {
    // Cleanup WebSocket khi component unmount
    return () => {
      wsService.disconnect();
      wsService.clearHandlers();
    };
  }, []);

  useEffect(() => {
    if (conversationId && messages.length > 0 && window.saveConversation) {
      // Don't save if we're loading a conversation
      if (isLoadingConversation.current) {
        return;
      }

      // Debounce save to avoid excessive re-renders
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }

      saveTimeoutRef.current = setTimeout(() => {
        const userMsg = messages.filter((m) => m.type === "user").pop();
        const assistantMsg = messages
          .filter((m) => m.type === "assistant")
          .pop();

        // Only move to top if the last message is from user (new message sent)
        const lastMsg = messages[messages.length - 1];
        const shouldMoveToTop = lastMsg?.type === "user";

        window.saveConversation!(
          conversationId,
          userMsg?.content || "New conversation",
          assistantMsg?.content || "Response received",
          messages,
          shouldMoveToTop
        );
      }, 100); // Save after 100ms of inactivity (faster to prevent data loss)
    }
  }, [messages, conversationId]);

  const messageQueue = React.useRef<QueueItem[]>([]);
  const isProcessingQueue = React.useRef(false);

  

  const processQueue = useCallback(async () => {
    if (isProcessingQueue.current) {
      return;
    }
    isProcessingQueue.current = true;

    while (messageQueue.current.length > 0) {
      const item = messageQueue.current.shift();

      if (!item) {
        continue;
      }


      // Handle Final Response
      if (item.type === "final_response") {
        const { response, queryId, conversationId: itemConversationId } = item;

        setMessages((prevMessages) => {
          const filtered = prevMessages.filter(
            (msg) => msg.id !== `${queryId}-thinking`
          );

          let layout: LayoutField[] | undefined;
          let fullData: unknown;
          let contentText = "";

          if (response) {
            if (typeof response === "string") {
              contentText = response;
            } else if (typeof response === "object") {
              // Response is now directly the chat response (no final_response wrapper)
              const chatResponse =
                (response as Record<string, any>).response || response;

              if (chatResponse?.layout) {
                layout = chatResponse.layout;
                fullData = chatResponse.full_data;
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
          const thinkingMsg = prevMessages.find(
            (msg) => msg.id === `${queryId}-thinking`
          );
          if (
            thinkingMsg &&
            thinkingMsg.updates &&
            thinkingMsg.updates.length > 0
          ) {
            messagesToAdd.push({
              ...thinkingMsg,
              id: `${queryId}-thinking-display`,
              isThinkingExpanded: true,
            });
          }

          if (contentText || layout) {
            messagesToAdd.push({
              id: `${queryId}-answer`,
              type: "assistant",
              content: contentText,
              timestamp: new Date(),
              layout: layout,
            } as Message);
          }

          return [...filtered, ...messagesToAdd];
        });

        setLoading(false);

        // Fetch quick actions immediately after query completes
        // Note: Orchestrator generates quick actions BEFORE sending final response,
        // so they're already in cache - fetch immediately!
        if (itemConversationId) {
          console.log("[ChatInterface] ✅ Fetching quick actions immediately");
          fetchQuickActions(itemConversationId); // Orchestrator already generated fresh ones in cache
        } else {
          console.warn("[ChatInterface] ❌ Cannot fetch quick actions - conversationId is undefined in item!");
        }

        // Save conversation immediately after final response
        if (itemConversationId && window.saveConversation) {
          console.log(
            "[ChatInterface] Saving conversation after final response:",
            itemConversationId
          );
          // Use setTimeout to ensure state has updated
          setTimeout(() => {
            setMessages((currentMessages) => {
              if (currentMessages.length > 0) {
                const userMsg = currentMessages
                  .filter((m) => m.type === "user")
                  .pop();
                const assistantMsg = currentMessages
                  .filter((m) => m.type === "assistant")
                  .pop();

                console.log(
                  "[ChatInterface] Messages to save:",
                  currentMessages.length,
                  "User msg:",
                  userMsg?.content.slice(0, 30),
                  "Assistant msg:",
                  assistantMsg?.content?.slice(0, 30) || "layout response"
                );

                window.saveConversation!(
                  itemConversationId,
                  userMsg?.content || "New conversation",
                  assistantMsg?.content || "Response received",
                  currentMessages,
                  false // Don't move to top for final response
                );

                // No need to navigate again - already navigated when message was sent
              }
              return currentMessages;
            });
          }, 100);
        }

        continue;
      }

      // Handle WebSocket Message
      const { message, queryId } = item;

      // HITL: Handle approval messages - add as update in thinking process
      if (message.type === "approval_required") {
        const approvalRequest = message.data as ApprovalRequest;

        console.log("[ChatInterface] 📨 Received approval_required:", {
          approval_id: approvalRequest.approval_id,
          tool_name: approvalRequest.tool_name,
          queryId,
        });

        // AUTO MODE: Automatically approve without user interaction
        if (hitlMode === "auto") {
          const autoApprovalResponse: ApprovalResponse = {
            approval_id: approvalRequest.approval_id,
            query_id: approvalRequest.query_id,
            action: "approve",
            modified_params: undefined,
          };

          // Send auto-approval to backend via REST API (more reliable)
          try {
            await apiService.submitApprovalResponse(autoApprovalResponse);
            console.log(
              "[ChatInterface] ✅ Auto-approval sent successfully via REST API"
            );
          } catch (error) {
            console.error(
              "[ChatInterface] ❌ Failed to send auto-approval:",
              error
            );
            addToast("Failed to send auto-approval to backend", "error");
          }

          // Mark as resolved immediately
          setResolvedApprovals((prev) => {
            const newMap = new Map(prev);
            newMap.set(approvalRequest.approval_id, "approve");
            return newMap;
          });

          // Add auto-approved update to thinking process
          const autoApprovedUpdate: TaskUpdate = {
            type: "approval_required",
            agent_type: approvalRequest.agent_type,
            status: "auto_approved",
            approval: approvalRequest,
            timestamp: message.timestamp,
          };

          setMessages((prev) => {
            const hasThinkingMsg = prev.some(
              (msg) => msg.id === `${queryId}-thinking`
            );
            if (!hasThinkingMsg) {
              return [
                ...prev,
                {
                  id: `${queryId}-thinking`,
                  type: "system",
                  content: "",
                  timestamp: new Date(),
                  updates: [autoApprovedUpdate],
                },
              ];
            }
            return prev.map((msg) => {
              if (msg.id === `${queryId}-thinking`) {
                // Check for duplicate approval
                const existingApproval = msg.updates?.find(
                  (u: any) =>
                    u.approval?.approval_id === approvalRequest.approval_id
                );

                if (existingApproval) {
                  console.log(
                    "[ChatInterface] ⚠️ Duplicate auto-approval detected, skipping:",
                    approvalRequest.approval_id
                  );
                  return msg;
                }

                return {
                  ...msg,
                  updates: [...(msg.updates || []), autoApprovedUpdate],
                };
              }
              return msg;
            });
          });

          continue;
        }

        // REVIEW MODE: Show approval card for manual approval
        const approvalUpdate: TaskUpdate = {
          type: "approval_required",
          agent_type: approvalRequest.agent_type,
          status: "pending_approval",
          approval: approvalRequest,
          timestamp: message.timestamp,
        };

        // Add to thinking message updates (prevent duplicates)
        setMessages((prev) => {
          const hasThinkingMsg = prev.some(
            (msg) => msg.id === `${queryId}-thinking`
          );
          if (!hasThinkingMsg) {
            return [
              ...prev,
              {
                id: `${queryId}-thinking`,
                type: "system",
                content: "",
                timestamp: new Date(),
                updates: [approvalUpdate],
              },
            ];
          }
          return prev.map((msg) => {
            if (msg.id === `${queryId}-thinking`) {
              // Check if this approval already exists in updates
              const existingApproval = msg.updates?.find(
                (u: any) =>
                  u.approval?.approval_id === approvalRequest.approval_id
              );

              if (existingApproval) {
                console.log(
                  "[ChatInterface] ⚠️ Duplicate approval request detected, skipping:",
                  approvalRequest.approval_id
                );
                return msg; // Don't add duplicate
              }

              return {
                ...msg,
                updates: [...(msg.updates || []), approvalUpdate],
              };
            }
            return msg;
          });
        });

        // Scroll to show approval card
        setTimeout(() => {
          messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }, 100);

        continue;
      }

      if (message.type === "approval_resolved") {
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
        case "orchestrator":
          uiUpdate = {
            ...message.data,
            agent_type: message.data.agent_type || "orchestrator",
          };
          break;
        case "tool_execution":
          uiUpdate = {
            agent_type: message.data.agent_type || "worker",
            status: "done",
            result: {
              tool_results: [
                {
                  tool_name: message.data.tool_name,
                  parameters: message.data.parameters,
                  tool_result: message.data.result,
                },
              ],
            },
            timestamp: message.timestamp,
          };
          break;
        case "thinking": {
          // Check if this is orchestrator reasoning step (has step + explanation + conclusion)
          const isOrchestratorReasoning =
            message.data.step !== undefined &&
            message.data.explanation !== undefined &&
            message.data.conclusion !== undefined;
          if (isOrchestratorReasoning) {
            uiUpdate = {
              agent_type: message.data.agent_type || "orchestrator",
              type: "reasoning_step",
              status: "processing",
              step: message.data.step,
              explanation: message.data.explanation,
              conclusion: message.data.conclusion,
              timestamp: message.timestamp,
            };
          } else {
            // Regular thinking message (worker agents)
            uiUpdate = {
              agent_type: message.data.agent_type || "worker",
              status: "processing",
              message: message.data.reasoning,
              timestamp: message.timestamp,
            };
          }
          break;
        }
        case "task_update":
          uiUpdate = message.data;
          break;
        case "error":
          uiUpdate = {
            agent_type: message.data.agent_type || "system",
            status: "failed",
            message: message.data.error,
            timestamp: message.timestamp,
          };
          break;
      }

      if (uiUpdate) {
        // Special handling for Typing Effect on 'thinking' messages
        if (message.type === "thinking" && uiUpdate.message) {
          const fullText = uiUpdate.message;
          let currentText = "";
          const chunkSize = 45; // bigger chunk to reduce re-renders
          const minFlushGap = 60; // ms
          let lastFlush = performance.now();

          // Create the update object initially with empty message
          const updateId = generateId();
          const initialUpdate = { ...uiUpdate, message: "", id: updateId };

          // Add the empty update first
          setMessages((prev) => {
            const hasThinkingMsg = prev.some(
              (msg) => msg.id === `${queryId}-thinking`
            );
            if (!hasThinkingMsg) {
              return [
                ...prev,
                {
                  id: `${queryId}-thinking`,
                  type: "system",
                  content: "",
                  timestamp: new Date(),
                  updates: [initialUpdate],
                },
              ];
            }
            return prev.map((msg) =>
              msg.id === `${queryId}-thinking`
                ? {
                    ...msg,
                    updates: [...(msg.updates || []), initialUpdate],
                  }
                : msg
            );
          });

          // Type out the text
          for (let i = 0; i < fullText.length; i += chunkSize) {
            currentText += fullText.slice(i, i + chunkSize);
            const now = performance.now();

            // Throttle state updates to avoid jitter
            if (
              now - lastFlush >= minFlushGap ||
              i + chunkSize >= fullText.length
            ) {
              setMessages((prev) =>
                prev.map((msg) => {
                  if (msg.id !== `${queryId}-thinking`) return msg;
                  const updates = msg.updates || [];
                  const newUpdates = updates.map((u) =>
                    (u as any).id === updateId
                      ? { ...u, message: currentText }
                      : u
                  );
                  return {
                    ...msg,
                    updates: newUpdates,
                    isThinkingExpanded:
                      msg.isThinkingExpanded === undefined
                        ? true
                        : msg.isThinkingExpanded,
                  };
                })
              );

              lastFlush = now;
              await new Promise((r) => setTimeout(r, 25));
            }
          }
        } else {
          // Non-typing updates (immediate)
          setMessages((prev) => {
            const hasThinkingMsg = prev.some(
              (msg) => msg.id === `${queryId}-thinking`
            );
            if (!hasThinkingMsg) {
              return [
                ...prev,
                {
                  id: `${queryId}-thinking`,
                  type: "system",
                  content: "",
                  timestamp: new Date(),
                  updates: [uiUpdate],
                },
              ];
            }
            return prev.map((msg) =>
              msg.id === `${queryId}-thinking`
                ? {
                    ...msg,
                    updates: [...(msg.updates || []), uiUpdate],
                  }
                : msg
            );
          });
        }

        // Small delay between messages to prevent UI jitter
        await new Promise((r) => setTimeout(r, 100));
      }
    }

    isProcessingQueue.current = false;
  }, [hitlMode]);

  const addToQueue = useCallback(
    (item: any) => {
      messageQueue.current.push(item);
      processQueue();
    },
    [processQueue]
  );

  const handleSendMessage = useCallback(
    async (inputText: string) => {
      if (!inputText.trim() || loading) return;

      const queryId = generateId();
      let currentConversationId = conversationId;

      if (!currentConversationId) {
        currentConversationId = queryId;
        setConversationId(currentConversationId);
        // Mark this conversation as newly created to skip loading
        skipLoadForNewConversation.current = currentConversationId;

        // Navigate immediately to show URL and highlight sidebar
        if (onConversationChange) {
          onConversationChange(currentConversationId);
        }

        // Create new conversation entry in sidebar immediately
        if (window.createNewConversation) {
          window.createNewConversation(
            currentConversationId,
            inputText.slice(0, 50)
          );
        }
      }

      const userMessage: Message = {
        id: queryId,
        type: "user",
        content: inputText,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMessage]);
      const queryText = inputText;
      setLoading(true);

      try {
        // Only disconnect if WebSocket is for a different query
        const currentQueryId = wsService.getQueryId();
        console.log("[ChatInterface] 📡 WebSocket state:", {
          currentQueryId,
          newQueryId: queryId,
          isConnected: wsService.isConnected(),
        });

        // Always clear old handlers and reconnect for new query
        wsService.clearHandlers();
        wsService.connect(queryId);

        wsService.onMessage((message) => {
          addToQueue({ message, queryId });
        });

        wsService.onClose(() => {
          console.log("[ChatInterface] WebSocket closed for query:", queryId);
        });

        wsService.onError((error) => {
          console.error("[ChatInterface] WebSocket error:", error);
        });

        await new Promise((resolve) => setTimeout(resolve, 100));

        const response = await apiService.submitQuery(
          queryId,
          queryText,
          currentConversationId,
          useCache
        );

        // Push final response to queue
        addToQueue({
          type: "final_response",
          response,
          queryId,
          isNewConversation: false, // Don't navigate again
          conversationId: currentConversationId,
        });
      } catch (error) {
        console.error("Failed to send message:", error);
        setLoading(false);
        addToast("Failed to send message. Please try again.", "error");
      }
    },
    [loading, conversationId, addToQueue, addToast, onConversationChange, useCache]
  );

  // Render graph/chart
  const renderGraph = (field: LayoutField, index: number) => {
    if (!field.data) {
      console.log('[renderGraph] No data for field:', field);
      return null;
    }

    console.log('[renderGraph]', {
      graph_type: field.graph_type,
      data_keys: Object.keys(field.data),
      hasChartData: 'chartData' in field.data,
      hasLabels: 'labels' in field.data,
      data: field.data
    });

    // Better color palette
    const COLORS = [
      "#667eea",
      "#764ba2",
      "#f093fb",
      "#4facfe",
      "#43e97b",
      "#fa709a",
      "#ffa502",
      "#26c485",
    ];

    // Custom tooltip
    const CustomTooltip = ({ active, payload }: any) => {
      if (active && payload && payload.length) {
        return (
          <div className="chart-tooltip">
            <p className="tooltip-label">
              {payload[0].name || payload[0].payload.name}
            </p>
            <p className="tooltip-value">
              {payload[0].value || payload[0].payload.value}
            </p>
          </div>
        );
      }
      return null;
    };

    if (field.graph_type === "piechart") {
      // Transform data for PieChart
      if (!field.data.labels) return null;
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
                label={({ name, percent }: any) =>
                  `${name}: ${(percent * 100).toFixed(0)}%`
                }
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((_entry, i) => (
                  <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                content={<CustomTooltip />}
                cursor={{ fill: "rgba(255, 255, 255, 0.1)" }}
              />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (field.graph_type === "barchart") {
      // Transform data for BarChart
      if (!field.data.labels) return null;
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
              <XAxis
                dataKey="name"
                stroke="#666666"
                style={{ fontSize: "0.8rem" }}
              />
              <YAxis stroke="#666666" style={{ fontSize: "0.8rem" }} />
              <Tooltip
                content={<CustomTooltip />}
                cursor={{ fill: "rgba(255, 255, 255, 0.05)" }}
              />
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

    if (field.graph_type === "linechart") {
      // Transform data for LineChart (for trends)
      if (!field.data.labels) return null;
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
              <XAxis
                dataKey="name"
                stroke="#666666"
                style={{ fontSize: "0.8rem" }}
              />
              <YAxis stroke="#666666" style={{ fontSize: "0.8rem" }} />
              <Tooltip
                content={<CustomTooltip />}
                cursor={{ fill: "rgba(255, 255, 255, 0.05)" }}
              />
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

    if (field.graph_type === 'horizontalbarchart') {
      // Horizontal BarChart - uses Recharts format {chartData, dataKey, nameKey}
      if (!field.data.chartData || !Array.isArray(field.data.chartData)) {
        console.warn('[horizontalbarchart] Missing chartData array');
        return null;
      }

      const chartData = field.data.chartData;
      const dataKey = (field.data.dataKey as string) || 'value';
      const nameKey = (field.data.nameKey as string) || 'name';

      console.log('[horizontalbarchart] Rendering with:', {
        chartDataLength: chartData.length,
        dataKey,
        nameKey,
        firstItem: chartData[0]
      });

      // Dynamic height: more space per item for readability
      const chartHeight = Math.max(400, chartData.length * 45);

      // Format number helper
      const formatNumber = (value: number) => {
        if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
        if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
        return value.toString();
      };

      return (
        <div key={index} className="layout-graph" style={{ marginTop: '1.5rem', marginBottom: '1.5rem' }}>
          {field.title && <h4 style={{ marginBottom: '1.25rem', fontSize: '1rem' }}>{field.title}</h4>}
          {field.description && <p style={{ marginBottom: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>{field.description}</p>}
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart 
              data={chartData} 
              layout="vertical"
              margin={{ top: 10, right: 30, left: 20, bottom: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" opacity={0.5} />
              <XAxis 
                type="number" 
                stroke="#888888" 
                style={{ fontSize: '0.85rem' }}
                tickFormatter={formatNumber}
              />
              <YAxis 
                type="category" 
                dataKey={nameKey}
                stroke="#888888" 
                style={{ fontSize: '0.85rem' }} 
                width={180}
                tick={{ fill: '#aaaaaa' }}
              />
              <Tooltip 
                content={<CustomTooltip />} 
                cursor={{ fill: 'rgba(102, 126, 234, 0.1)' }}
                contentStyle={{
                  backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-primary)',
                  borderRadius: '6px',
                  fontSize: '0.85rem'
                }}
              />
              <Legend 
                wrapperStyle={{ paddingTop: '15px' }}
                iconType="rect"
              />
              <Bar 
                dataKey={dataKey}
                fill={COLORS[0]}
                radius={[0, 6, 6, 0]}
                barSize={25}
                animationDuration={800}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    }

    if (field.graph_type === 'scatterplot') {
      // ScatterPlot - Recharts format
      if (!field.data.scatterData || !Array.isArray(field.data.scatterData)) {
        console.warn('[scatterplot] Missing scatterData array');
        return null;
      }

      const scatterData = field.data.scatterData;
      const xKey = (field.data.xKey as string) || 'x';
      const yKey = (field.data.yKey as string) || 'y';
      const nameKey = field.data.nameKey as string | undefined;
      const groupKey = field.data.groupKey as string | undefined;
      const groups = field.data.groups as string[] | undefined;

      console.log('[scatterplot] Rendering:', {
        points: scatterData.length,
        xKey,
        yKey,
        hasGroups: !!groupKey,
        groups: groups?.length || 0
      });

      // Group data by group_field if exists
      const groupedData: Record<string, any[]> = {};
      
      if (groupKey && groups) {
        // Initialize groups
        groups.forEach(g => { groupedData[g] = []; });
        // Distribute points
        scatterData.forEach(point => {
          const group = point[groupKey] as string || 'Ungrouped';
          if (!groupedData[group]) groupedData[group] = [];
          groupedData[group].push(point);
        });
      } else {
        // No grouping - single scatter
        groupedData['All'] = scatterData;
      }

      const chartHeight = 450;

      // Custom scatter tooltip
      const ScatterTooltip = ({ active, payload }: any) => {
        if (active && payload && payload.length > 0) {
          const data = payload[0].payload;
          return (
            <div className="chart-tooltip" style={{
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-primary)',
              borderRadius: '6px',
              padding: '0.75rem',
              fontSize: '0.85rem'
            }}>
              {nameKey && data[nameKey] && <p className="tooltip-label" style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{data[nameKey]}</p>}
              <p className="tooltip-value" style={{ margin: '0.15rem 0' }}>X: <strong>{data[xKey]?.toLocaleString()}</strong></p>
              <p className="tooltip-value" style={{ margin: '0.15rem 0' }}>Y: <strong>{data[yKey]?.toLocaleString()}</strong></p>
              {groupKey && data[groupKey] && <p className="tooltip-group" style={{ marginTop: '0.25rem', color: 'var(--text-secondary)' }}>Group: {data[groupKey]}</p>}
            </div>
          );
        }
        return null;
      };

      return (
        <div key={index} className="layout-graph" style={{ marginTop: '1.5rem', marginBottom: '1.5rem' }}>
          {field.title && <h4 style={{ marginBottom: '1.25rem', fontSize: '1rem' }}>{field.title}</h4>}
          {field.description && <p style={{ marginBottom: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>{field.description}</p>}
          <ResponsiveContainer width="100%" height={chartHeight}>
            <ScatterChart margin={{ top: 20, right: 30, bottom: 20, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" opacity={0.5} />
              <XAxis 
                type="number" 
                dataKey={xKey}
                stroke="#888888" 
                style={{ fontSize: '0.85rem' }}
                name={xKey}
              />
              <YAxis 
                type="number" 
                dataKey={yKey}
                stroke="#888888" 
                style={{ fontSize: '0.85rem' }}
                name={yKey}
              />
              <ZAxis range={[60, 400]} />
              <Tooltip 
                content={<ScatterTooltip />}
                cursor={{ strokeDasharray: '3 3' }}
              />
              {groups && groups.length > 1 && <Legend wrapperStyle={{ paddingTop: '15px' }} />}
              
              {Object.entries(groupedData).map(([groupName, points], i) => (
                <Scatter
                  key={groupName}
                  name={groupName}
                  data={points}
                  fill={COLORS[i % COLORS.length]}
                  shape="circle"
                  animationDuration={800}
                />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      );
    }

    return null;
  };

  // Render layout field
  const renderLayoutField = (field: LayoutField, index: number) => {
    switch (field.field_type) {
      case "markdown":
        return (
          <div key={index} className="layout-markdown">
            <ReactMarkdown>{field.content || ""}</ReactMarkdown>
          </div>
        );

      case "table":
        return (
          <div key={index} className="layout-table">
            {field.title && <h4>{field.title}</h4>}
            {field.data && field.data.headers && field.data.rows && (
              <PaginatedTable 
                headers={field.data.headers} 
                rows={field.data.rows}
                totalItems={field.data.totalItems}
              />
            )}
          </div>
        );

      case "graph":
        return renderGraph(field, index);

      default:
        return null;
    }
  };

  // Generic helper function to extract tool result summary
  const extractToolResultSummary = (toolResult: any): string => {
    // Handle string results
    if (typeof toolResult === "string") {
      return toolResult;
    }

    // Handle object results - check for common summary patterns
    if (typeof toolResult === "object" && toolResult !== null) {
      // Pattern 1: Check for 'summary' field (most tools follow this)
      if (toolResult.summary) {
        const summary = toolResult.summary;

        // Generic: count common fields
        const commonCountFields = [
          "total_items",
          "total_movements",
          "total_alerts",
          "total_value",
          "total_results",
          "count",
          "total",
        ];

        for (const field of commonCountFields) {
          if (field in summary && typeof summary[field] === "number") {
            // Format the field name nicely
            const fieldLabel = field
              .replace(/total_/g, "")
              .replace(/_/g, " ")
              .replace(/\b\w/g, (l) => l.toUpperCase());
            return `Found ${summary[field]} ${fieldLabel}`;
          }
        }

        // Pattern 2: Check for status-based summaries
        if (
          summary.out_of_stock !== undefined ||
          summary.critical_stock !== undefined
        ) {
          const alerts = [
            summary.out_of_stock && `${summary.out_of_stock} out of stock`,
            summary.critical_stock && `${summary.critical_stock} critical`,
            summary.low_stock && `${summary.low_stock} low stock`,
          ].filter(Boolean);
          if (alerts.length > 0) {
            return `Alerts: ${alerts.join(", ")}`;
          }
        }

        // Pattern 3: Generic summary fallback
        const summaryStr = JSON.stringify(summary).substring(0, 100);
        return summaryStr.length > 0 ? summaryStr : "Operation successful";
      }

      // Pattern 4: Direct fields (no summary wrapper)
      const directCountFields = [
        "stock_level",
        "available_qty",
        "current_stock",
        "total_value",
        "items",
      ];

      for (const field of directCountFields) {
        if (field in toolResult) {
          const value = toolResult[field];
          if (typeof value === "number") {
            const fieldLabel = field
              .replace(/_/g, " ")
              .replace(/\b\w/g, (l) => l.toUpperCase());
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
    return "Success";
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        {onToggleSidebar && (
          <button
            className="sidebar-toggle-btn"
            onClick={onToggleSidebar}
            title={isSidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
        )}
        <h2>Multi-Agent Stock Management</h2>
        <div className="header-actions">
          {conversationId && (
            <span className="conversation-id">
              Conversation: {conversationId.slice(0, 8)}
            </span>
          )}
          <button
            className="info-btn"
            onClick={() => setShowInfoModal(true)}
            title="Hướng dẫn sử dụng"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 16v-4M12 8h.01"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Info Modal */}
      {showInfoModal && (
        <div className="info-modal-overlay" onClick={() => setShowInfoModal(false)}>
          <div className="info-modal" onClick={(e) => e.stopPropagation()}>
            <div className="info-modal-header">
              <h3>Hướng dẫn sử dụng</h3>
              <button className="info-modal-close" onClick={() => setShowInfoModal(false)}>×</button>
            </div>
            <div className="info-modal-content">
              <div className="info-section">
                <h4>Inventory Agent</h4>
                <ul>
                  <li>Kiểm tra tồn kho theo sản phẩm hoặc kho</li>
                  <li>Xem lịch sử nhập/xuất kho</li>
                  <li>Đề xuất điều chuyển hàng giữa các kho</li>
                  <li>Tạo phiếu điều chuyển kho</li>
                </ul>
              </div>
              <div className="info-section">
                <h4>Analytics Agent</h4>
                <ul>
                  <li>Phân tích sản phẩm bán chạy nhất</li>
                  <li>Phân tích sản phẩm bán chậm</li>
                  <li>So sánh doanh số giữa các kỳ</li>
                  <li>Phân tích Pareto (80/20)</li>
                  <li>Phân tích độ phủ tồn kho</li>
                </ul>
              </div>
              <div className="info-section">
                <h4>Forecasting Agent</h4>
                <ul>
                  <li>Dự báo doanh số tháng tới</li>
                  <li>Dự báo nhu cầu tồn kho</li>
                </ul>
              </div>
              <div className="info-section">
                <h4>Ordering Agent</h4>
                <ul>
                  <li>Kiểm tra nhu cầu bổ sung hàng</li>
                  <li>Tính toán số lượng đặt hàng tối ưu</li>
                  <li>Chọn nhà cung cấp tốt nhất</li>
                  <li>Tạo đơn đặt hàng</li>
                  <li>Theo dõi biến động giá</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="chat-messages" ref={chatMessagesRef}>
        <div>
          {messages.map((message, _messageIndex) => (
            <div key={message.id} className={`message message-${message.type}`}>
              <div className="message-content">
                {/* Hiển thị layout nếu có */}
                {message.layout && message.layout.length > 0 ? (
                  <div className="structured-response">
                    {message.layout.map((field, index) =>
                      renderLayoutField(field, index)
                    )}
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
                  open={message.isThinkingExpanded ?? false}
                  onToggle={(e) => {
                    if ((e.target as HTMLDetailsElement).open) {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === message.id
                            ? { ...m, isThinkingExpanded: true }
                            : m
                        )
                      );
                    } else {
                      setMessages((prev) =>
                        prev.map((m) =>
                          m.id === message.id
                            ? { ...m, isThinkingExpanded: false }
                            : m
                        )
                      );
                    }
                  }}
                >
                  <summary
                    className="thinking-header"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <svg
                      className="thinking-icon"
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="2"
                        d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                      />
                    </svg>
                    <span className="thinking-title">Thinking Process</span>
                    <span className="thinking-toggle">
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                      >
                        <path d="M4.427 9.427l3.396 3.396a.25.25 0 00.354 0l3.396-3.396A.25.25 0 0011.396 9H4.604a.25.25 0 00-.177.427z" />
                      </svg>
                    </span>
                  </summary>
                  <div className="thinking-content">
                    {message.updates.map((update, index) => {
                      // Skip approval cards - render them separately below
                      if (
                        (update as any).type === "approval_required" &&
                        (update as any).approval
                      ) {
                        return null;
                      }

                      // Parse agent-specific information
                      const agentName = update.agent_type
                        ? update.agent_type.charAt(0).toUpperCase() +
                          update.agent_type.slice(1).replace("_", " ")
                        : "Agent";

                      const isWorker =
                        update.agent_type &&
                        !["orchestrator"].includes(update.agent_type);
                      const isOrchestrator =
                        update.agent_type === "orchestrator";
                      const isReasoningStep =
                        (update as any).type === "reasoning_step";

                      // Reasoning step - render like normal step
                      if (isReasoningStep) {
                        return (
                          <div key={index} className="thinking-step processing">
                            <div className="step-header">
                              <span className="step-agent">{agentName}</span>
                              <span className="step-name">{update.step}</span>
                              <span className="step-status processing">
                                ...
                              </span>
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
                        <div
                          key={index}
                          className={`thinking-step ${update.status}`}
                        >
                          <div className="step-header">
                            <span className="step-agent">{agentName}</span>
                            {update.step && (
                              <span className="step-name">{update.step}</span>
                            )}
                            <span className={`step-status ${update.status}`}>
                              {update.status === "done" && "✓"}
                              {update.status === "processing" && "..."}
                              {update.status === "failed" && "✗"}
                            </span>
                          </div>

                          {update.message && (
                            <div className="step-message">{update.message}</div>
                          )}

                          {update.sub_query && (
                            <div className="step-query">{update.sub_query}</div>
                          )}

                          {/* Show tool results for worker agents */}
                          {update.result &&
                            isWorker &&
                            typeof update.result === "object" && (
                              <div className="step-tools">
                                {update.result.tool_results &&
                                  update.result.tool_results.length > 0 && (
                                    <>
                                      <strong>Tool Calls:</strong>
                                      {update.result.tool_results.map(
                                        (tool: any, toolIndex: number) => (
                                          <div
                                            key={toolIndex}
                                            className="tool-call"
                                          >
                                            <div className="tool-name">
                                              {tool.tool_name}
                                            </div>
                                            <div className="tool-params">
                                              <strong>Parameters:</strong>
                                              <pre>
                                                {JSON.stringify(
                                                  tool.parameters,
                                                  null,
                                                  2
                                                )}
                                              </pre>
                                            </div>
                                            {tool.tool_result && (
                                              <details className="tool-result-details">
                                                <summary className="tool-result-summary">
                                                  <strong>Result:</strong>{" "}
                                                  {extractToolResultSummary(
                                                    tool.tool_result
                                                  )}
                                                  <span className="result-toggle">
                                                    ▼
                                                  </span>
                                                </summary>
                                                <div className="tool-result-full">
                                                  <pre>
                                                    {JSON.stringify(
                                                      tool.tool_result,
                                                      null,
                                                      2
                                                    )}
                                                  </pre>
                                                </div>
                                              </details>
                                            )}
                                          </div>
                                        )
                                      )}
                                    </>
                                  )}
                              </div>
                            )}

                          {/* Show orchestrator planning info */}
                          {isOrchestrator && update.agents_needed && update.agents_needed.length > 0 && (
                            <div className="orchestrator-planning">
                              <div className="planning-agents">
                                <span className="planning-label">Agents:</span>
                                <div className="agent-badges">
                                  {update.agents_needed.map((agent: string) => (
                                    <span key={agent} className="agent-badge">
                                      {agent}
                                    </span>
                                  ))}
                                </div>
                              </div>
                              {update.task_dependency && (
                                <div className="planning-tasks">
                                  {Object.entries(update.task_dependency).map(([agentType, tasks]: [string, any]) => (
                                    <div key={agentType} className="task-group">
                                      {(tasks as any[]).map((task: any, idx: number) => (
                                        <div key={task.task_id || idx} className="task-item">
                                          <span className="task-query">{task.sub_query}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ))}
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

              {/* Render approval cards separately below thinking process */}
              {message.updates &&
                message.updates.some(
                  (u: any) => u.type === "approval_required" && u.approval
                ) && (
                  <div className="approval-cards-container">
                    {message.updates
                      .filter(
                        (u: any) => u.type === "approval_required" && u.approval
                      )
                      .map((update: any) => {
                        const approval = update.approval as ApprovalRequest;
                        const isResolved = resolvedApprovals.has(
                          approval.approval_id
                        );
                        const resolvedAction = resolvedApprovals.get(
                          approval.approval_id
                        );

                        return (
                          <ApprovalCard
                            key={`approval-${approval.approval_id}`}
                            approval={approval}
                            onRespond={handleApprovalResponse}
                            isResolved={isResolved}
                            resolvedAction={resolvedAction}
                          />
                        );
                      })}
                  </div>
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
      </div>

      <div className="chat-input-container">
        {quickActions.length > 0 && (
          <QuickActionPills
            suggestions={quickActions}
            onSelectSuggestion={handleSendMessage}
            loading={loading}
          />
        )}
        <ChatInput onSendMessage={handleSendMessage} loading={loading} />
      </div>

      <Toast toasts={toasts} onRemove={removeToast} />
    </div>
  );
};

export default ChatInterface;
