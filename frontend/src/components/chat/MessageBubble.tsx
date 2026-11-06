import { memo, useRef, useState, type MouseEvent, type PointerEvent, type TouchEvent } from "react";
import { AlertCircle, Clock, Eye, EyeOff, Loader2, Plane, PlaneLanding, Reply, Trash2 } from "lucide-react";
import { formatTime } from "../../lib/format";
import type { ChatMessage, RevealedEntry } from "../../types";

/** What a reply bubble shows about the message it answers. */
export interface ReplyQuote {
  senderName: string | null;
  /** The original's text, or null if it's no longer available (deleted / cleared / not loaded). */
  text: string | null;
  /** Local id of the original, for jumping to it (null if it isn't in this view). */
  targetId: string | null;
  /** The original was deleted for everyone. */
  deleted?: boolean;
}

interface MessageBubbleProps {
  message: ChatMessage;
  isOwn: boolean;
  senderName: string;
  quote?: ReplyQuote;
  revealed?: RevealedEntry;
  decrypting: boolean;
  highlighted: boolean;
  onReveal: (id: string) => void;
  onHide: (id: string) => void;
  onReply: (id: string) => void;
  onJumpTo: (id: string) => void;
  /** Present only when this user may delete the message (their own). */
  onDelete?: (id: string) => Promise<void>;
}

const SWIPE_TRIGGER_PX = 56;
const SWIPE_MAX_PX = 84;

function StatusIcon({ status }: { status: ChatMessage["status"] }) {
  if (status === "sending") return <Clock className="size-3.5" aria-label="Sending" />;
  if (status === "sent") return <Plane className="size-3.5" aria-label="Sent" />;
  if (status === "failed") return <AlertCircle className="size-3.5 text-red-300" aria-label="Not sent" />;
  return <PlaneLanding className="size-3.5 text-amber-300" aria-label="Delivered" />;
}

/** Hidden view: a neutral mask the length of the message, never the text itself. */
function maskFor(length: number): string {
  return "•".repeat(Math.min(40, Math.max(6, length)));
}

/**
 * Swipe a bubble to the right to reply, like WhatsApp: finger on phones, mouse drag on computers.
 * The gesture only takes over once movement is clearly horizontal, so scrolling and button
 * clicks inside the bubble keep working.
 */
function useSwipeToReply(onReply: () => void) {
  const [offset, setOffset] = useState(0);
  const start = useRef<{ x: number; y: number; axis: "x" | "y" | null } | null>(null);
  const armed = useRef(false);
  const dragged = useRef(false);

  function begin(x: number, y: number) {
    start.current = { x, y, axis: null };
    armed.current = false;
    dragged.current = false;
  }

  /** Returns true while a horizontal swipe is in progress. */
  function move(x: number, y: number): boolean {
    const s = start.current;
    if (!s) return false;
    const dx = x - s.x;
    const dy = y - s.y;
    if (s.axis === null && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
      s.axis = Math.abs(dx) > Math.abs(dy) && dx > 0 ? "x" : "y";
      if (s.axis === "x") window.getSelection()?.removeAllRanges();
    }
    if (s.axis !== "x") return false;
    dragged.current = true;
    const next = Math.max(0, Math.min(dx, SWIPE_MAX_PX));
    setOffset(next);
    if (next >= SWIPE_TRIGGER_PX && !armed.current) {
      armed.current = true;
      navigator.vibrate?.(12);
    }
    return true;
  }

  function end() {
    if (armed.current) onReply();
    start.current = null;
    armed.current = false;
    setOffset(0);
  }

  return {
    offset,
    handlers: {
      // Touch (phones)
      onTouchStart: (e: TouchEvent) => begin(e.touches[0].clientX, e.touches[0].clientY),
      onTouchMove: (e: TouchEvent) => void move(e.touches[0].clientX, e.touches[0].clientY),
      onTouchEnd: end,
      onTouchCancel: end,
      // Mouse (computers)
      onPointerDown(e: PointerEvent) {
        if (e.pointerType === "mouse" && e.button === 0) begin(e.clientX, e.clientY);
      },
      onPointerMove(e: PointerEvent) {
        if (e.pointerType !== "mouse" || !start.current) return;
        // Capture only once it's really a swipe, so plain clicks still reach their buttons.
        if (move(e.clientX, e.clientY) && !e.currentTarget.hasPointerCapture(e.pointerId)) {
          e.currentTarget.setPointerCapture(e.pointerId);
        }
      },
      onPointerUp(e: PointerEvent) {
        if (e.pointerType === "mouse" && start.current) end();
      },
      onPointerCancel(e: PointerEvent) {
        if (e.pointerType === "mouse" && start.current) end();
      },
      // A drag shouldn't also count as a click on whatever was under the pointer.
      onClickCapture(e: MouseEvent) {
        if (dragged.current) {
          e.preventDefault();
          e.stopPropagation();
          dragged.current = false;
        }
      },
    },
  };
}

export const MessageBubble = memo(function MessageBubble({
  message,
  isOwn,
  senderName,
  quote,
  revealed,
  decrypting,
  highlighted,
  onReveal,
  onHide,
  onReply,
  onJumpTo,
  onDelete,
}: MessageBubbleProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const time = formatTime(message.sentAt);
  const canReply = message.serverId !== null;
  const swipe = useSwipeToReply(() => canReply && onReply(message.id));

  async function handleDelete() {
    if (!onDelete || deleting) return;
    setDeleting(true);
    setDeleteFailed(false);
    try {
      await onDelete(message.id); // on success this bubble unmounts
    } catch {
      setDeleting(false);
      setDeleteFailed(true);
    }
  }

  const bubbleColors = isOwn
    ? "bg-gradient-to-br from-sky-500 to-sky-700 text-white dark:from-sky-600 dark:to-sky-800"
    : "bg-white text-slate-900 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700";
  const muted = isOwn ? "text-sky-100/80" : "text-slate-400 dark:text-slate-500";
  const actionBtn = `inline-flex h-7 items-center gap-1 rounded-full px-2 text-xs font-medium transition active:scale-95 ${
    isOwn ? "hover:bg-white/15" : "hover:bg-slate-100 dark:hover:bg-slate-700"
  }`;
  const quoteColors = isOwn
    ? "border-amber-300 bg-white/15 text-sky-50"
    : "border-sky-500 bg-sky-50 text-slate-700 dark:bg-slate-900/60 dark:text-slate-300";

  return (
    <div
      id={`msg-${message.id}`}
      className={`animate-fade-up relative flex ${isOwn ? "justify-end" : "justify-start"} ${swipe.offset ? "cursor-grabbing select-none" : ""}`}
      style={{ touchAction: "pan-y" }}
      {...swipe.handlers}
    >
      {/* Reply hint revealed behind the bubble while swiping */}
      {swipe.offset > 0 && (
        <span
          className="absolute left-1 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-full bg-sky-600/90 text-white"
          style={{ opacity: Math.min(1, swipe.offset / SWIPE_TRIGGER_PX) }}
          aria-hidden="true"
        >
          <Reply className="size-4" />
        </span>
      )}

      <article
        className={`relative max-w-[85%] overflow-hidden rounded-2xl px-3.5 pb-1.5 pt-2.5 shadow-sm sm:max-w-[75%] ${bubbleColors} ${
          isOwn ? "rounded-br-sm" : "rounded-bl-sm"
        } ${highlighted ? "animate-highlight" : ""}`}
        style={{
          transform: swipe.offset ? `translateX(${swipe.offset}px)` : undefined,
          transition: swipe.offset ? "none" : "transform 180ms ease-out",
        }}
        aria-label={`${revealed ? "Message" : "Hidden message"} from ${senderName} at ${time}`}
      >
        {quote && (
          <button
            type="button"
            onClick={() => quote.targetId && onJumpTo(quote.targetId)}
            disabled={!quote.targetId}
            className={`mb-1.5 block w-full rounded-lg border-l-4 px-2.5 py-1.5 text-left text-xs ${quoteColors}`}
          >
            <span className="block font-semibold">{quote.senderName ?? "Message"}</span>
            <span className="line-clamp-2 opacity-90">
              {quote.deleted ? (
                <i>This message was deleted</i>
              ) : quote.text === null ? (
                <i>Original message unavailable</i>
              ) : revealed ? (
                quote.text
              ) : (
                <span className="masked font-mono" aria-label="Hidden">
                  {maskFor(quote.text.length)}
                </span>
              )}
            </span>
          </button>
        )}

        {revealed && revealed.text === null ? (
          <p className="text-[13px] italic leading-snug" role="alert">
            {revealed.error ?? "This message can't be shown."}
          </p>
        ) : revealed ? (
          <p className="whitespace-pre-wrap break-words text-[15px] leading-snug">{revealed.text}</p>
        ) : (
          <>
            <p className={`masked font-mono text-[12px] leading-relaxed ${muted}`} aria-hidden="true">
              {maskFor(message.body.length)}
            </p>
            <span className="sr-only">Content hidden</span>
          </>
        )}

        {confirmDelete ? (
          <div className="mt-2 flex items-center justify-end gap-1 text-xs">
            <span className={`mr-auto ${deleteFailed ? "text-red-300" : muted}`} aria-live="polite">
              {deleteFailed ? "Couldn't delete. Try again?" : "Delete for both of you?"}
            </span>
            <button
              type="button"
              className={actionBtn}
              onClick={() => {
                setConfirmDelete(false);
                setDeleteFailed(false);
              }}
              disabled={deleting}
            >
              Cancel
            </button>
            <button
              type="button"
              className={`${actionBtn} ${isOwn ? "text-red-100" : "text-red-500"}`}
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting && <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />}
              Delete
            </button>
          </div>
        ) : (
          <div className="mt-1.5 flex items-center gap-0.5">
            {decrypting ? (
              <span className={`${actionBtn} ${muted}`}>
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
              </span>
            ) : revealed ? (
              <button type="button" className={actionBtn} onClick={() => onHide(message.id)}>
                <EyeOff className="size-3.5" aria-hidden="true" />
                Hide
              </button>
            ) : (
              <button type="button" className={actionBtn} onClick={() => onReveal(message.id)}>
                <Eye className="size-3.5" aria-hidden="true" />
                Reveal
              </button>
            )}
            {canReply && (
              <button
                type="button"
                className={`${actionBtn} ${muted}`}
                onClick={() => onReply(message.id)}
                aria-label="Reply"
                title="Reply (or swipe right)"
              >
                <Reply className="size-3.5" />
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                className={`${actionBtn} ${muted}`}
                onClick={() => setConfirmDelete(true)}
                aria-label="Delete message"
              >
                <Trash2 className="size-3.5" />
              </button>
            )}
            <span className={`ml-auto flex items-center gap-1 pl-2 text-[11px] ${muted}`}>
              <time dateTime={new Date(message.sentAt).toISOString()}>{time}</time>
              {isOwn && <StatusIcon status={message.status} />}
            </span>
          </div>
        )}

        {revealed && (
          <div
            key={revealed.expiresAt}
            className={`reveal-timer absolute inset-x-0 bottom-0 h-0.5 ${isOwn ? "bg-amber-300/70" : "bg-sky-400/60"}`}
            style={{ animationDuration: `${Math.max(0, revealed.expiresAt - Date.now())}ms` }}
            aria-hidden="true"
          />
        )}
      </article>
    </div>
  );
});
