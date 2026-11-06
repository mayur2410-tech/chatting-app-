/** Wire types shared with the backend. Full description: docs/websocket-protocol.md. */

export interface MessageDto {
  id: string;
  seq: number;
  conversationId: string;
  senderId: string;
  clientMessageId: string;
  body: string;
  replyToId: string | null;
  /** Copy of what the reply quotes (body is empty if the original was deleted). */
  replyTo: { id: string; senderId: string; body: string; deleted: boolean } | null;
  createdAt: string;
  deliveredAt: string | null;
}

// --- client → server ---

export interface SendEvent {
  type: "message.send";
  clientMessageId: string;
  body: string;
  replyToId: string | null;
}

export interface DeliveredEvent {
  type: "message.delivered";
  messageIds: string[];
}

export type ClientEvent =
  | SendEvent
  | DeliveredEvent
  | { type: "typing"; isTyping: boolean }
  | { type: "presence"; state: "active" | "away" }
  | { type: "ping" };

// --- server → client ---

export type ServerErrorCode =
  | "invalid_json"
  | "invalid_event"
  | "invalid_reply"
  | "payload_too_large"
  | "unsupported_data"
  | "rate_limited"
  | "session_expired"
  | "internal_error";

export type ServerEvent =
  | { type: "message.new"; message: MessageDto }
  | { type: "message.ack"; clientMessageId: string; message: MessageDto }
  | { type: "message.delivered"; messageId: string; deliveredAt: string }
  | { type: "message.deleted"; messageId: string; senderId: string; clientMessageId: string }
  | { type: "conversation.cleared"; clearedThroughSeq: number }
  | { type: "typing"; userId: string; isTyping: boolean }
  | { type: "presence"; userId: string; online: boolean; lastSeenAt: string | null }
  | { type: "error"; code: ServerErrorCode; message: string; clientMessageId?: string; retryAfter?: number }
  | { type: "pong" };

export const MAX_DELIVERED_BATCH = 100;
