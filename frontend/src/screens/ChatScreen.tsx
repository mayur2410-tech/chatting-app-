import { useCallback, useEffect, useState } from "react";
import { Eraser } from "lucide-react";
import { ChatHeader } from "../components/chat/ChatHeader";
import { Composer, type ReplyDraft } from "../components/chat/Composer";
import { MessageList } from "../components/chat/MessageList";
import { Button } from "../components/ui";
import { REVEAL_TIMEOUT_MS } from "../config";
import { useRevealState } from "../hooks/useRevealState";
import type { ConversationApi } from "../messaging/useConversation";
import type { Participant } from "../types";

interface ChatScreenProps {
  me: Participant;
  conversation: ConversationApi;
  onSignOut: () => void;
}

const UNKNOWN_PARTNER: Participant = { id: "", displayName: "…" };

function ClearChatDialog({
  partnerName,
  onCancel,
  onConfirm,
}: {
  partnerName: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-4 sm:items-center" onClick={onCancel}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="clear-title"
        aria-describedby="clear-desc"
        className="animate-fade-up safe-bottom w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="flex size-11 items-center justify-center rounded-full bg-sky-100 dark:bg-sky-950">
          <Eraser className="size-5 text-sky-700 dark:text-sky-300" aria-hidden="true" />
        </span>
        <h2 id="clear-title" className="mt-3 text-base font-semibold">
          Clear this chat?
        </h2>
        <p id="clear-desc" className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          All messages will be removed from <b>your</b> view only. {partnerName} will still see the whole conversation.
        </p>
        {failed && <p className="mt-2 text-sm text-red-600 dark:text-red-400">Couldn't clear the chat. Try again.</p>}
        <div className="mt-5 flex gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setFailed(false);
              try {
                await onConfirm();
              } catch {
                setFailed(true);
                setBusy(false);
              }
            }}
          >
            Clear chat
          </Button>
        </div>
      </div>
    </div>
  );
}

/** "Name is typing…" bubble shown just above the message box. */
function TypingIndicator({ name }: { name: string }) {
  return (
    <div className="chart-grid shrink-0 px-3 pb-1.5 pt-1" aria-live="polite">
      <div className="animate-fade-up inline-flex items-center gap-2 rounded-2xl rounded-bl-sm bg-white px-3 py-2 text-xs text-slate-500 shadow-sm ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700">
        <span className="flex gap-1" aria-hidden="true">
          <span className="size-1.5 animate-bounce rounded-full bg-sky-500 [animation-delay:-0.3s]" />
          <span className="size-1.5 animate-bounce rounded-full bg-sky-500 [animation-delay:-0.15s]" />
          <span className="size-1.5 animate-bounce rounded-full bg-sky-500" />
        </span>
        {name} is typing…
      </div>
    </div>
  );
}

/**
 * All readable text lives in useRevealState inside this component, so unmounting it
 * (sign-out) discards every revealed message.
 */
export function ChatScreen({ me, conversation, onSignOut }: ChatScreenProps) {
  const { messages, decode } = conversation;
  const { revealed, pending, reveal, hide, hideAll } = useRevealState(REVEAL_TIMEOUT_MS, decode);
  const [replyToId, setReplyToId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const partner = conversation.partner ?? UNKNOWN_PARTNER;

  // Drop readable text (and a pending reply) for messages that no longer exist.
  useEffect(() => {
    const live = new Set(messages.map((m) => m.id));
    revealed.forEach((_, id) => {
      if (!live.has(id)) hide(id);
    });
    if (replyToId && !live.has(replyToId)) setReplyToId(null);
  }, [messages, revealed, hide, replyToId]);

  const revealOne = useCallback((id: string) => void reveal([id]), [reveal]);

  const revealAll = useCallback(() => {
    void reveal(messages.filter((m) => !revealed.has(m.id)).map((m) => m.id));
  }, [messages, revealed, reveal]);

  const deleteMessage = useCallback(
    async (id: string) => {
      await conversation.remove(id);
      hide(id);
    },
    [conversation, hide],
  );

  const replyTarget = replyToId ? messages.find((m) => m.id === replyToId) : undefined;
  const replyDraft: ReplyDraft | null = replyTarget
    ? {
        id: replyTarget.id,
        senderName: replyTarget.senderId === me.id ? "yourself" : partner.displayName,
        preview: revealed.get(replyTarget.id)?.text ?? "Hidden message",
      }
    : null;

  const send = useCallback(
    (text: string) => {
      conversation.send(text, replyTarget?.serverId ?? null);
      setReplyToId(null);
    },
    [conversation, replyTarget],
  );

  const signOut = useCallback(() => {
    hideAll();
    onSignOut();
  }, [hideAll, onSignOut]);

  return (
    <div className="app-shell mx-auto flex w-full max-w-2xl flex-col sm:border-x sm:border-sky-900/10 sm:shadow-xl dark:sm:border-white/10">
      <ChatHeader
        partner={partner}
        connection={conversation.connection}
        partnerStatus={conversation.partnerStatus}
        revealedCount={revealed.size}
        totalCount={messages.length}
        onRevealAll={revealAll}
        onHideAll={hideAll}
        onClearChat={() => setConfirmClear(true)}
        onSignOut={signOut}
      />
      <MessageList
        status={conversation.status}
        messages={messages}
        me={me}
        partner={partner}
        revealed={revealed}
        pending={pending}
        hasOlder={conversation.hasOlder}
        loadingOlder={conversation.loadingOlder}
        onLoadOlder={() => void conversation.loadOlder()}
        onRetry={conversation.retry}
        onReveal={revealOne}
        onHide={hide}
        onReply={setReplyToId}
        onDelete={deleteMessage}
      />
      {conversation.partnerStatus.typing && <TypingIndicator name={partner.displayName} />}
      <Composer
        onSend={send}
        replyTo={replyDraft}
        onCancelReply={() => setReplyToId(null)}
        onTyping={conversation.notifyTyping}
        onStopTyping={conversation.stopTyping}
        disabled={conversation.status !== "ready"}
        placeholder="Message"
      />
      {confirmClear && (
        <ClearChatDialog
          partnerName={partner.displayName}
          onCancel={() => setConfirmClear(false)}
          onConfirm={async () => {
            await conversation.clear();
            hideAll();
            setReplyToId(null);
            setConfirmClear(false);
          }}
        />
      )}
    </div>
  );
}
