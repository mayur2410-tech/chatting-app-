import type { MessageDto } from "../messaging/protocol";
import { apiRequest } from "./client";

export interface ConversationMember {
  id: string;
  displayName: string;
  /** Has the chat open and visible right now. */
  online: boolean;
  lastSeenAt: string | null;
}

export interface Conversation {
  id: string;
  members: ConversationMember[];
  createdAt: string;
}

export interface ConversationList {
  conversations: Conversation[];
  maxBodyChars: number;
}

export interface MessagePage {
  messages: MessageDto[];
  hasMore: boolean;
  syncedAt: string;
}

export interface Deletions {
  deleted: Array<{ id: string; senderId: string; clientMessageId: string }>;
  syncedAt: string;
}

export function fetchConversations(): Promise<ConversationList> {
  return apiRequest("GET", "/conversations");
}

export function fetchMessages(
  conversationId: string,
  cursor: { before?: number; after?: number } = {},
  limit = 50,
): Promise<MessagePage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor.before !== undefined) params.set("before", String(cursor.before));
  if (cursor.after !== undefined) params.set("after", String(cursor.after));
  return apiRequest("GET", `/conversations/${encodeURIComponent(conversationId)}/messages?${params}`);
}

export function fetchDeletions(conversationId: string, since: string): Promise<Deletions> {
  const params = new URLSearchParams({ since });
  return apiRequest("GET", `/conversations/${encodeURIComponent(conversationId)}/deletions?${params}`);
}

/** Deletes for both users. Only the sender may delete. */
export function deleteMessage(messageId: string): Promise<void> {
  return apiRequest("DELETE", `/messages/${encodeURIComponent(messageId)}`);
}

/** Clears the chat for the current user only; the partner keeps the full history. */
export function clearConversation(conversationId: string): Promise<{ clearedThroughSeq: number }> {
  return apiRequest("POST", `/conversations/${encodeURIComponent(conversationId)}/clear`);
}
