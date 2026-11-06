import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthUser } from "../api/auth";
import { ApiError } from "../api/client";
import { clearConversation, deleteMessage, fetchConversations, fetchDeletions, fetchMessages } from "../api/messages";
import type { ChatMessage, DecodeResult, Participant } from "../types";
import { MAX_DELIVERED_BATCH, type MessageDto, type ServerEvent } from "./protocol";
import { ChatSocket, type SocketStatus } from "./socket";

export type ConversationStatus = "loading" | "ready" | "no-conversation" | "error";

/** What the header shows under the partner's name. */
export interface PartnerStatus {
  online: boolean;
  /** Epoch ms of when they were last online, if ever. */
  lastSeenAt: number | null;
  typing: boolean;
}

export interface ConversationApi {
  status: ConversationStatus;
  partner: Participant | null;
  partnerStatus: PartnerStatus;
  messages: ChatMessage[];
  connection: SocketStatus;
  hasOlder: boolean;
  loadingOlder: boolean;
  send: (text: string, replyToId: string | null) => void;
  /** Delete one of your own messages for both of you. */
  remove: (id: string) => Promise<void>;
  /** Clear the chat for you only; your partner keeps the full history. */
  clear: () => Promise<void>;
  loadOlder: () => Promise<void>;
  /** Text of one message for the Reveal view; null if it no longer exists. */
  decode: (id: string) => Promise<DecodeResult | null>;
  retry: () => void;
  /** Call on every keystroke in the composer; sends throttled "typing" updates. */
  notifyTyping: () => void;
  /** Call when the message is sent or the box is cleared. */
  stopTyping: () => void;
}

const ACK_RESEND_MS = 10_000;
/** While typing, re-announce at most this often. */
const TYPING_SEND_INTERVAL_MS = 2_500;
/** Stop "typing" after this long without a keystroke. */
const TYPING_IDLE_MS = 4_000;
/** Hide the partner's "typing…" if no update arrives within this time (e.g. their tab died). */
const TYPING_EXPIRE_MS = 6_000;

const OFFLINE: PartnerStatus = { online: false, lastSeenAt: null, typing: false };

function parseTime(iso: string | null): number | null {
  return iso ? Date.parse(iso) : null;
}

function keyOf(senderId: string, clientMessageId: string): string {
  return `${senderId}:${clientMessageId}`;
}

function fromDto(dto: MessageDto): ChatMessage {
  return {
    id: keyOf(dto.senderId, dto.clientMessageId),
    serverId: dto.id,
    clientMessageId: dto.clientMessageId,
    senderId: dto.senderId,
    sentAt: Date.parse(dto.createdAt),
    body: dto.body,
    replyToId: dto.replyToId,
    replyPreview: dto.replyTo
      ? { senderId: dto.replyTo.senderId, body: dto.replyTo.body, deleted: dto.replyTo.deleted }
      : null,
    status: dto.deliveredAt ? "delivered" : "sent",
    seq: dto.seq,
  };
}

function compare(a: ChatMessage, b: ChatMessage): number {
  // Stored messages by server order; unsent ones after them, by local send time.
  if (a.seq !== null && b.seq !== null) return a.seq - b.seq;
  if (a.seq !== null) return -1;
  if (b.seq !== null) return 1;
  return a.sentAt - b.sentAt;
}

/** Upsert by stable key; never downgrade a delivered message back to sent. */
function merge(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  if (incoming.length === 0) return current;
  const byKey = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) {
    const existing = byKey.get(m.id);
    byKey.set(m.id, existing?.status === "delivered" ? { ...m, status: "delivered" } : m);
  }
  return [...byKey.values()].sort(compare);
}

/**
 * Real-time conversation state: history over HTTP, live events over the WebSocket, an in-memory
 * outbox with idempotent retries (client message ids), and catch-up after every reconnect.
 */
export function useConversation(user: AuthUser | null, onSessionProblem: () => void): ConversationApi {
  const [status, setStatus] = useState<ConversationStatus>("loading");
  const [partner, setPartner] = useState<Participant | null>(null);
  const [partnerStatus, setPartnerStatus] = useState<PartnerStatus>(OFFLINE);
  const [messages, setMessagesState] = useState<ChatMessage[]>([]);
  const [connection, setConnection] = useState<SocketStatus>("closed");
  const [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const messagesRef = useRef<ChatMessage[]>([]);
  const conversationIdRef = useRef<string | null>(null);
  const syncedAtRef = useRef<string | null>(null);
  const socketRef = useRef<ChatSocket | null>(null);
  const timersRef = useRef<number[]>([]);
  /** Keys of unsent messages the user deleted; if an ack still arrives, delete on the server too. */
  const cancelledRef = useRef<Set<string>>(new Set());
  const typingExpireRef = useRef<number | undefined>(undefined);
  const typingSentAtRef = useRef(0);
  const typingIdleRef = useRef<number | undefined>(undefined);
  const sessionProblemRef = useRef(onSessionProblem);
  sessionProblemRef.current = onSessionProblem;

  const userId = user?.id ?? null;

  const commit = useCallback((next: ChatMessage[]) => {
    messagesRef.current = next;
    setMessagesState(next);
  }, []);

  const update = useCallback(
    (fn: (prev: ChatMessage[]) => ChatMessage[]) => commit(fn(messagesRef.current)),
    [commit],
  );

  const later = useCallback((fn: () => void, ms: number) => {
    timersRef.current.push(window.setTimeout(fn, ms));
  }, []);

  const handleApiError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) sessionProblemRef.current();
  }, []);

  // --- outbound ---

  const transmit = useCallback(
    (m: ChatMessage) => {
      const sent = socketRef.current?.send({
        type: "message.send",
        clientMessageId: m.clientMessageId,
        body: m.body,
        replyToId: m.replyToId,
      });
      // If no ack arrives in time, resend; the server de-duplicates by clientMessageId.
      if (sent) {
        later(() => {
          const current = messagesRef.current.find((x) => x.id === m.id);
          if (current?.status === "sending") transmit(current);
        }, ACK_RESEND_MS);
      }
    },
    [later],
  );

  const flushOutbox = useCallback(() => {
    if (!userId) return;
    messagesRef.current.filter((m) => m.senderId === userId && m.status === "sending").forEach(transmit);
  }, [userId, transmit]);

  /** Tell the server which incoming messages this device has received. */
  const acknowledgeReceived = useCallback(() => {
    if (!userId) return;
    const pending = messagesRef.current.filter(
      (m) => m.senderId !== userId && m.serverId !== null && m.status !== "delivered",
    );
    const acked = new Set<string>();
    for (let i = 0; i < pending.length; i += MAX_DELIVERED_BATCH) {
      const batch = pending.slice(i, i + MAX_DELIVERED_BATCH);
      const ok = socketRef.current?.send({ type: "message.delivered", messageIds: batch.map((m) => m.serverId!) });
      if (!ok) break;
      batch.forEach((m) => acked.add(m.id));
    }
    if (acked.size > 0) update((prev) => prev.map((m) => (acked.has(m.id) ? { ...m, status: "delivered" } : m)));
  }, [userId, update]);

  const removeLocal = useCallback(
    (match: (m: ChatMessage) => boolean) => update((prev) => prev.filter((m) => !match(m))),
    [update],
  );

  /** Hide every stored message up to `through` (this user's "Clear chat" point). */
  const applyClear = useCallback(
    (through: number) => {
      removeLocal((m) => m.seq !== null && m.seq <= through);
      setHasOlder(false);
    },
    [removeLocal],
  );

  // --- presence & typing ---

  const setPartnerTyping = useCallback((typing: boolean) => {
    window.clearTimeout(typingExpireRef.current);
    setPartnerStatus((s) => (s.typing === typing ? s : { ...s, typing }));
    if (typing) typingExpireRef.current = window.setTimeout(() => setPartnerTyping(false), TYPING_EXPIRE_MS);
  }, []);

  /** Tell the server whether this tab currently shows the chat (drives "online" for the partner). */
  const reportPresence = useCallback(() => {
    socketRef.current?.send({ type: "presence", state: document.visibilityState === "visible" ? "active" : "away" });
  }, []);

  const refreshPartnerPresence = useCallback(async () => {
    const { conversations } = await fetchConversations();
    const other = conversations[0]?.members.find((m) => m.id !== userId);
    if (other) {
      setPartnerStatus((s) => ({ ...s, online: other.online, lastSeenAt: parseTime(other.lastSeenAt) }));
    }
  }, [userId]);

  // --- catch-up after (re)connect ---

  const catchUp = useCallback(async () => {
    const conversationId = conversationIdRef.current;
    if (!conversationId) return;
    reportPresence();
    try {
      // 0. The partner may have come and gone while we were disconnected.
      await refreshPartnerPresence();
      // 1. Messages stored while we were disconnected.
      let after = messagesRef.current.reduce((max, m) => (m.seq !== null && m.seq > max ? m.seq : max), 0);
      for (;;) {
        const page = await fetchMessages(conversationId, { after }, 100);
        update((prev) => merge(prev, page.messages.map(fromDto)));
        if (!page.hasMore || page.messages.length === 0) break;
        after = page.messages[page.messages.length - 1].seq;
      }
      // 2. Deletions made while we were disconnected.
      if (syncedAtRef.current) {
        const { deleted, syncedAt } = await fetchDeletions(conversationId, syncedAtRef.current);
        const gone = new Set(deleted.map((d) => d.id));
        if (gone.size > 0) removeLocal((m) => m.serverId !== null && gone.has(m.serverId));
        syncedAtRef.current = syncedAt;
      }
    } catch (err) {
      handleApiError(err);
    }
    flushOutbox();
    acknowledgeReceived();
  }, [update, removeLocal, flushOutbox, acknowledgeReceived, handleApiError, reportPresence, refreshPartnerPresence]);

  // --- inbound events ---

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case "message.ack": {
          const message = fromDto(event.message);
          if (cancelledRef.current.has(message.id)) {
            cancelledRef.current.delete(message.id);
            deleteMessage(event.message.id).catch(handleApiError);
            return;
          }
          update((prev) => merge(prev, [message]));
          return;
        }
        case "message.new": {
          update((prev) => merge(prev, [fromDto(event.message)]));
          if (event.message.senderId !== userId) {
            setPartnerTyping(false); // their message arrived, so they're done typing
            acknowledgeReceived();
          }
          return;
        }
        case "typing":
          if (event.userId !== userId) setPartnerTyping(event.isTyping);
          return;
        case "presence":
          if (event.userId === userId) return;
          setPartnerStatus((s) => ({
            online: event.online,
            lastSeenAt: parseTime(event.lastSeenAt) ?? s.lastSeenAt,
            typing: event.online ? s.typing : false,
          }));
          return;
        case "message.delivered":
          update((prev) => prev.map((m) => (m.serverId === event.messageId ? { ...m, status: "delivered" } : m)));
          return;
        case "message.deleted": {
          const key = keyOf(event.senderId, event.clientMessageId);
          removeLocal((m) => m.serverId === event.messageId || m.id === key);
          return;
        }
        case "conversation.cleared":
          applyClear(event.clearedThroughSeq); // cleared in another of this user's tabs
          return;
        case "error": {
          if (event.code === "session_expired") return; // the socket closes with 4401 next
          if (!event.clientMessageId || !userId) return;
          const key = keyOf(userId, event.clientMessageId);
          if (event.code === "rate_limited") {
            later(() => {
              const m = messagesRef.current.find((x) => x.id === key);
              if (m?.status === "sending") transmit(m);
            }, (event.retryAfter ?? 2) * 1000);
            return;
          }
          update((prev) => prev.map((m) => (m.id === key && m.status === "sending" ? { ...m, status: "failed" } : m)));
          return;
        }
        default:
          return;
      }
    },
    [userId, update, removeLocal, applyClear, acknowledgeReceived, transmit, later, handleApiError, setPartnerTyping],
  );

  // Keep socket callbacks pointing at the latest closures.
  const handlersRef = useRef({ handleEvent, catchUp });
  handlersRef.current = { handleEvent, catchUp };

  // --- lifecycle: load, connect, tear down on sign-out ---

  useEffect(() => {
    if (!userId) return;
    let disposed = false;
    setStatus("loading");

    (async () => {
      try {
        const { conversations } = await fetchConversations();
        if (disposed) return;
        const conversation = conversations[0];
        if (!conversation) {
          setStatus("no-conversation");
          return;
        }
        conversationIdRef.current = conversation.id;
        const other = conversation.members.find((m) => m.id !== userId);
        setPartner(other ? { id: other.id, displayName: other.displayName } : null);
        if (other) setPartnerStatus({ online: other.online, lastSeenAt: parseTime(other.lastSeenAt), typing: false });

        const page = await fetchMessages(conversation.id);
        if (disposed) return;
        commit(page.messages.map(fromDto));
        setHasOlder(page.hasMore);
        syncedAtRef.current = page.syncedAt;
        setStatus("ready");

        const socket = new ChatSocket({
          onEvent: (e) => handlersRef.current.handleEvent(e),
          onOpen: () => void handlersRef.current.catchUp(),
          onStatus: setConnection,
          onConnectFailed: () => sessionProblemRef.current(),
          onSessionEnded: () => sessionProblemRef.current(),
        });
        socketRef.current = socket;
        socket.start();
      } catch (err) {
        if (disposed) return;
        handleApiError(err);
        setStatus("error");
      }
    })();

    return () => {
      disposed = true;
      socketRef.current?.stop();
      socketRef.current = null;
      timersRef.current.forEach((t) => window.clearTimeout(t));
      timersRef.current = [];
      cancelledRef.current.clear();
      conversationIdRef.current = null;
      syncedAtRef.current = null;
      commit([]);
      setPartner(null);
      setPartnerStatus(OFFLINE);
      window.clearTimeout(typingExpireRef.current);
      window.clearTimeout(typingIdleRef.current);
      typingSentAtRef.current = 0;
      setHasOlder(false);
      setConnection("closed");
    };
  }, [userId, reloadToken, commit, handleApiError]);

  // Report visibility changes so the partner sees "online" only while the chat is on screen.
  useEffect(() => {
    if (!userId) return;
    document.addEventListener("visibilitychange", reportPresence);
    return () => document.removeEventListener("visibilitychange", reportPresence);
  }, [userId, reportPresence]);

  // --- actions ---

  const stopTyping = useCallback(() => {
    window.clearTimeout(typingIdleRef.current);
    if (typingSentAtRef.current) {
      socketRef.current?.send({ type: "typing", isTyping: false });
      typingSentAtRef.current = 0;
    }
  }, []);

  const notifyTyping = useCallback(() => {
    const now = Date.now();
    if (now - typingSentAtRef.current >= TYPING_SEND_INTERVAL_MS) {
      if (socketRef.current?.send({ type: "typing", isTyping: true })) typingSentAtRef.current = now;
    }
    window.clearTimeout(typingIdleRef.current);
    typingIdleRef.current = window.setTimeout(stopTyping, TYPING_IDLE_MS);
  }, [stopTyping]);

  const send = useCallback(
    (text: string, replyToId: string | null) => {
      if (!userId || !conversationIdRef.current) return;
      const clientMessageId = crypto.randomUUID();
      const original = replyToId ? messagesRef.current.find((m) => m.serverId === replyToId) : undefined;
      const message: ChatMessage = {
        id: keyOf(userId, clientMessageId),
        serverId: null,
        clientMessageId,
        senderId: userId,
        sentAt: Date.now(),
        body: text,
        replyToId,
        replyPreview: original ? { senderId: original.senderId, body: original.body, deleted: false } : null,
        status: "sending",
        seq: null,
      };
      stopTyping();
      update((prev) => merge(prev, [message]));
      transmit(message); // if offline, the outbox flushes on reconnect
    },
    [userId, update, transmit, stopTyping],
  );

  const remove = useCallback(
    async (id: string) => {
      const message = messagesRef.current.find((m) => m.id === id);
      if (!message) return;
      if (message.serverId === null) {
        if (message.status === "sending") cancelledRef.current.add(message.id);
        removeLocal((m) => m.id === id);
        return;
      }
      try {
        await deleteMessage(message.serverId);
        removeLocal((m) => m.id === id);
      } catch (err) {
        handleApiError(err);
        throw err;
      }
    },
    [removeLocal, handleApiError],
  );

  const clear = useCallback(async () => {
    const conversationId = conversationIdRef.current;
    if (!conversationId) return;
    try {
      const { clearedThroughSeq } = await clearConversation(conversationId);
      applyClear(clearedThroughSeq);
    } catch (err) {
      handleApiError(err);
      throw err;
    }
  }, [applyClear, handleApiError]);

  const loadOlder = useCallback(async () => {
    const conversationId = conversationIdRef.current;
    const oldest = messagesRef.current.find((m) => m.seq !== null)?.seq;
    if (!conversationId || oldest == null || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const page = await fetchMessages(conversationId, { before: oldest });
      update((prev) => merge(prev, page.messages.map(fromDto)));
      setHasOlder(page.hasMore);
      acknowledgeReceived();
    } catch (err) {
      handleApiError(err);
    } finally {
      setLoadingOlder(false);
    }
  }, [loadingOlder, update, acknowledgeReceived, handleApiError]);

  const decode = useCallback(async (id: string): Promise<DecodeResult | null> => {
    const message = messagesRef.current.find((m) => m.id === id);
    return message ? { ok: true, text: message.body } : null;
  }, []);

  const retry = useCallback(() => setReloadToken((n) => n + 1), []);

  return {
    status,
    partner,
    partnerStatus,
    messages,
    connection,
    hasOlder,
    loadingOlder,
    send,
    remove,
    clear,
    loadOlder,
    decode,
    retry,
    notifyTyping,
    stopTyping,
  };
}
