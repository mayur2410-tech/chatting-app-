import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PlaneTakeoff } from "lucide-react";
import { formatDayLabel, isSameDay } from "../../lib/format";
import { PlaneLoader, PlaneSpinner } from "../PlaneLoader";
import type { ConversationStatus } from "../../messaging/useConversation";
import type { ChatMessage, Participant, RevealedEntry } from "../../types";
import { MessageBubble, type ReplyQuote } from "./MessageBubble";

interface MessageListProps {
  status: ConversationStatus;
  messages: ChatMessage[];
  me: Participant;
  partner: Participant;
  revealed: Map<string, RevealedEntry>;
  pending: Set<string>;
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  onRetry: () => void;
  onReveal: (id: string) => void;
  onHide: (id: string) => void;
  onReply: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
}

const NEAR_BOTTOM_PX = 120;
const HIGHLIGHT_MS = 1600;

/** Date separator styled like an airport departures board. */
function DayChip({ label }: { label: string }) {
  return (
    <div className="my-2 flex justify-center">
      <span className="rounded-md bg-slate-900/85 px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-amber-300 shadow-sm dark:bg-black/60">
        {label}
      </span>
    </div>
  );
}

export function MessageList({
  status,
  messages,
  me,
  partner,
  revealed,
  pending,
  hasOlder,
  loadingOlder,
  onLoadOlder,
  onRetry,
  onReveal,
  onHide,
  onReply,
  onDelete,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLastId = useRef<string | null>(null);
  const wasNearBottom = useRef(true);
  /** Scroll geometry captured before older messages are prepended, to keep the view still. */
  const prependAnchor = useRef<{ height: number; top: number } | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const byServerId = useMemo(() => {
    const map = new Map<string, ChatMessage>();
    for (const m of messages) if (m.serverId) map.set(m.serverId, m);
    return map;
  }, [messages]);

  const nameOf = useCallback((senderId: string) => (senderId === me.id ? "You" : partner.displayName), [me.id, partner.displayName]);

  const quoteFor = useCallback(
    (m: ChatMessage): ReplyQuote | undefined => {
      if (!m.replyToId) return undefined;
      const target = byServerId.get(m.replyToId);
      if (target) return { senderName: nameOf(target.senderId), text: target.body, targetId: target.id };
      // Original not in this view (cleared, deleted, or not loaded yet): use the copy kept with the reply.
      const p = m.replyPreview;
      if (p) {
        return p.deleted
          ? { senderName: nameOf(p.senderId), text: null, targetId: null, deleted: true }
          : { senderName: nameOf(p.senderId), text: p.body, targetId: null };
      }
      return { senderName: null, text: null, targetId: null };
    },
    [byServerId, nameOf],
  );

  const jumpTo = useCallback((id: string) => {
    document.getElementById(`msg-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightId(id);
    window.setTimeout(() => setHighlightId((current) => (current === id ? null : current)), HIGHLIGHT_MS);
  }, []);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    wasNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
  };

  const loadOlder = () => {
    const el = scrollRef.current;
    if (el) prependAnchor.current = { height: el.scrollHeight, top: el.scrollTop };
    onLoadOlder();
  };

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const last = messages[messages.length - 1];
    const lastId = last?.id ?? null;

    if (prependAnchor.current && lastId === prevLastId.current) {
      // Older messages were added above: keep the same messages in view.
      el.scrollTop = prependAnchor.current.top + (el.scrollHeight - prependAnchor.current.height);
      prependAnchor.current = null;
    } else if (prevLastId.current === null && lastId !== null) {
      // First content: start at the latest message.
      el.scrollTop = el.scrollHeight;
    } else if (lastId !== prevLastId.current && (wasNearBottom.current || last?.senderId === me.id)) {
      // Follow new messages if the user was already at the bottom or sent the message themselves.
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
    prevLastId.current = lastId;
  }, [messages, me.id]);

  // Keep the bottom in view when the keyboard opens and the list shrinks.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (wasNearBottom.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  let placeholder: ReactNode = null;
  if (status === "loading") {
    placeholder = <PlaneLoader label="Loading messages…" />;
  } else if (status === "error") {
    placeholder = (
      <>
        <p className="text-sm">Couldn't load messages.</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-full bg-sky-600 px-4 py-1.5 text-sm font-medium text-white transition active:scale-95"
        >
          Try again
        </button>
      </>
    );
  } else if (status === "no-conversation") {
    placeholder = <p className="max-w-xs text-sm">The chat starts once both accounts have been set up.</p>;
  } else if (messages.length === 0) {
    placeholder = (
      <>
        <span className="flex size-14 items-center justify-center rounded-full bg-sky-100 dark:bg-sky-950">
          <PlaneTakeoff className="size-7 text-sky-600 dark:text-sky-400" aria-hidden="true" />
        </span>
        <p className="mt-3 text-sm font-medium text-slate-600 dark:text-slate-300">No messages yet</p>
        <p className="mt-1 text-xs">Say hello, you're cleared for takeoff.</p>
      </>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="chart-grid flex-1 overflow-y-auto overflow-x-hidden overscroll-contain px-3 py-4"
      role="log"
      aria-label="Conversation"
      aria-busy={status === "loading"}
    >
      {placeholder ? (
        <div className="flex h-full flex-col items-center justify-center text-center text-slate-400 dark:text-slate-500">
          {placeholder}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {hasOlder && (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={loadOlder}
                disabled={loadingOlder}
                className="inline-flex h-8 items-center gap-1.5 rounded-full bg-white/80 px-3 text-xs font-medium text-sky-700 shadow-sm transition active:scale-95 disabled:opacity-60 dark:bg-slate-800/80 dark:text-sky-300"
              >
                {loadingOlder && <PlaneSpinner className="size-4" />}
                Load earlier messages
              </button>
            </div>
          )}
          {messages.map((m, i) => {
            const showDay = i === 0 || !isSameDay(messages[i - 1].sentAt, m.sentAt);
            const isOwn = m.senderId === me.id;
            return (
              <Fragment key={m.id}>
                {showDay && <DayChip label={formatDayLabel(m.sentAt)} />}
                <MessageBubble
                  message={m}
                  isOwn={isOwn}
                  senderName={isOwn ? me.displayName : partner.displayName}
                  quote={quoteFor(m)}
                  revealed={revealed.get(m.id)}
                  decrypting={pending.has(m.id)}
                  highlighted={highlightId === m.id}
                  onReveal={onReveal}
                  onHide={onHide}
                  onReply={onReply}
                  onJumpTo={jumpTo}
                  onDelete={isOwn ? onDelete : undefined}
                />
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
