export type Screen = "restoring" | "login" | "chat";

export interface Participant {
  id: string;
  displayName: string;
}

/**
 * sending   — accepted locally, not yet confirmed stored by the server (queued / retried)
 * sent      — stored by the server (message.ack received)
 * delivered — received by the other person's device
 * failed    — rejected by the server; will not be retried
 */
export type DeliveryStatus = "sending" | "sent" | "delivered" | "failed";

export interface ChatMessage {
  /** Stable local key `${senderId}:${clientMessageId}`; unchanged when an optimistic send is acked. */
  id: string;
  /** Server id; null until the server has stored the message. */
  serverId: string | null;
  clientMessageId: string;
  senderId: string;
  sentAt: number;
  body: string;
  /** Server id of the message this one replies to. */
  replyToId: string | null;
  /** What the reply quotes, kept with the reply so it still shows if the original was cleared. */
  replyPreview: { senderId: string; body: string; deleted: boolean } | null;
  status: DeliveryStatus;
  /** Server ordering cursor; null while unsent. */
  seq: number | null;
}

/** A revealed message: its text, or why it could not be shown. */
export interface RevealedEntry {
  text: string | null;
  error?: string;
  expiresAt: number;
}

export type DecodeResult = { ok: true; text: string } | { ok: false; reason: string };
