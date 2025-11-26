const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8010';

export type MessageType = 
  | 'orchestrator'
  | 'tool_execution'
  | 'thinking'
  | 'task_update'
  | 'error';

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
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log('WebSocket connected for query:', queryId);
    };

    this.ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        this.messageHandlers.forEach((handler) => handler(message));
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.errorHandlers.forEach((handler) => handler(error));
    };

    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
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
}

export const wsService = new WebSocketService();
