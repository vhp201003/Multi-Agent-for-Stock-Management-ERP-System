const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8010";

export type MessageType =
  | "orchestrator"
  | "tool_execution"
  | "thinking"
  | "task_update"
  | "error"
  // HITL: Approval workflow messages
  | "approval_required"
  | "approval_resolved";

export interface WebSocketMessage {
  type: MessageType;
  data: any;
  timestamp: string;
}

export type MessageHandler = (message: WebSocketMessage) => void;
export type ErrorHandler = (error: Event) => void;
export type CloseHandler = () => void;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private queryId: string | null = null;
  private messageHandlers: MessageHandler[] = [];
  private errorHandlers: ErrorHandler[] = [];
  private closeHandlers: CloseHandler[] = [];

  connect(queryId: string): void {
    if (this.ws) {
      this.disconnect();
    }

    this.queryId = queryId;
    const wsUrl = `${WS_BASE_URL}/ws?query_id=${queryId}`;
    console.log("[WebSocket] 🔌 Connecting to:", wsUrl);
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("[WebSocket] ✅ Connected for query:", queryId);
    };

    this.ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        console.log("[WebSocket] 📨 Received message:", message.type, message);

        // Special logging for approval messages
        if (message.type === "approval_required") {
          console.warn("[WebSocket] 🔔 APPROVAL REQUIRED:", message.data);
        }

        this.messageHandlers.forEach((handler) => handler(message));
      } catch (error) {
        console.error("[WebSocket] ❌ Failed to parse message:", error);
      }
    };

    this.ws.onerror = (error) => {
      console.error("[WebSocket] ❌ Connection error:", error);
      this.errorHandlers.forEach((handler) => handler(error));
    };

    this.ws.onclose = () => {
      console.log("[WebSocket] 🔌 Disconnected");
      this.closeHandlers.forEach((handler) => handler());
      this.ws = null;
    };
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.queryId = null;
  }

  // HITL: Send message to backend
  send(message: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      console.log("[WebSocket] 📤 Sending message:", message.type);
      this.ws.send(JSON.stringify(message));
    } else {
      console.error(
        "[WebSocket] ❌ Cannot send - WebSocket not connected. ReadyState:",
        this.ws?.readyState
      );
    }
  }

  // HITL: Send approval response
  sendApprovalResponse(response: any): void {
    console.log("[WebSocket] 📤 Sending approval response:", response);
    this.send({
      type: "approval_response",
      data: response,
      timestamp: new Date().toISOString(),
    });
  }

  onMessage(handler: MessageHandler): void {
    this.messageHandlers.push(handler);
  }

  onError(handler: ErrorHandler): void {
    this.errorHandlers.push(handler);
  }

  onClose(handler: CloseHandler): void {
    this.closeHandlers.push(handler);
  }

  clearHandlers(): void {
    this.messageHandlers = [];
    this.errorHandlers = [];
    this.closeHandlers = [];
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  getQueryId(): string | null {
    return this.queryId;
  }
}

export const wsService = new WebSocketService();
