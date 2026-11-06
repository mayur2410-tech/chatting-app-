import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Keyboard, Reply, Send, Smile, X } from "lucide-react";
import { MAX_MESSAGE_LENGTH } from "../../config";
import { IconButton } from "../ui";
import { EmojiPicker } from "./EmojiPicker";

export interface ReplyDraft {
  /** Local id of the message being replied to (changes trigger focus). */
  id: string;
  senderName: string;
  /** Preview line; already masked by the caller if the message is hidden. */
  preview: string;
}

interface ComposerProps {
  onSend: (text: string) => void;
  replyTo?: ReplyDraft | null;
  onCancelReply?: () => void;
  /** Called on every edit while there is text (drives the partner's "typing…"). */
  onTyping?: () => void;
  /** Called when the box becomes empty. */
  onStopTyping?: () => void;
  disabled?: boolean;
  placeholder?: string;
}

const MAX_TEXTAREA_PX = 128;
const isTouch = typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;

export function Composer({
  onSend,
  replyTo,
  onCancelReply,
  onTyping,
  onStopTyping,
  disabled = false,
  placeholder = "Message",
}: ComposerProps) {
  const [text, setText] = useState("");
  const [showEmoji, setShowEmoji] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && text.trim().length > 0;

  // Auto-grow the textarea up to a few lines.
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
    el.style.overflowY = el.scrollHeight > MAX_TEXTAREA_PX ? "auto" : "hidden";
  }, [text]);

  // Starting a reply puts the cursor in the box, like WhatsApp.
  useEffect(() => {
    if (replyTo) {
      setShowEmoji(false);
      textareaRef.current?.focus();
    }
  }, [replyTo?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
    if (!showEmoji) textareaRef.current?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Desktop: Enter sends, Shift+Enter adds a line. Touch keyboards keep Enter as newline.
    if (e.key === "Enter" && !e.shiftKey && !isTouch && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape" && replyTo) {
      onCancelReply?.();
    }
  }

  function insertEmoji(emoji: string) {
    const el = textareaRef.current;
    const start = el?.selectionStart ?? text.length;
    const end = el?.selectionEnd ?? text.length;
    const next = (text.slice(0, start) + emoji + text.slice(end)).slice(0, MAX_MESSAGE_LENGTH);
    setText(next);
    requestAnimationFrame(() => {
      if (!el) return;
      const caret = start + emoji.length;
      el.setSelectionRange(caret, caret);
    });
  }

  function toggleEmoji() {
    // Opening the picker on mobile should dismiss the keyboard, and vice versa.
    if (showEmoji) {
      textareaRef.current?.focus();
    } else {
      textareaRef.current?.blur();
    }
    setShowEmoji(!showEmoji);
  }

  return (
    <div className="shrink-0 border-t border-sky-900/10 bg-white/95 backdrop-blur dark:border-white/10 dark:bg-slate-900/95">
      {replyTo && (
        <div className="animate-fade-up flex items-center gap-2 px-3 pt-2">
          <div className="min-w-0 flex-1 rounded-lg border-l-4 border-sky-500 bg-sky-50 px-3 py-1.5 dark:bg-slate-800">
            <p className="flex items-center gap-1 text-xs font-semibold text-sky-700 dark:text-sky-300">
              <Reply className="size-3.5" aria-hidden="true" />
              Replying to {replyTo.senderName}
            </p>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">{replyTo.preview}</p>
          </div>
          <IconButton
            onClick={onCancelReply}
            aria-label="Cancel reply"
            className="size-8 text-slate-500 hover:bg-slate-200/70 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="size-4" />
          </IconButton>
        </div>
      )}
      <form onSubmit={submit} className={`flex items-end gap-1.5 px-2 pt-2 ${showEmoji ? "pb-2" : "safe-bottom"}`}>
        <IconButton
          onClick={toggleEmoji}
          disabled={disabled}
          aria-label={showEmoji ? "Show keyboard" : "Emoji"}
          aria-expanded={showEmoji}
          className="text-slate-500 hover:bg-sky-100 dark:text-slate-400 dark:hover:bg-slate-800"
        >
          {showEmoji ? <Keyboard className="size-5" /> : <Smile className="size-5" />}
        </IconButton>
        <label htmlFor="composer" className="sr-only">
          Message
        </label>
        <textarea
          id="composer"
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (e.target.value.trim()) onTyping?.();
            else onStopTyping?.();
          }}
          onBlur={() => onStopTyping?.()}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowEmoji(false)}
          maxLength={MAX_MESSAGE_LENGTH}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          enterKeyHint="send"
          className="max-h-32 min-h-10 flex-1 resize-none rounded-2xl border border-slate-300 bg-slate-50 px-4 py-2 text-base leading-6 text-slate-900 placeholder:text-slate-400 outline-none transition focus:border-sky-500 focus:bg-white focus:ring-2 focus:ring-sky-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:bg-slate-900"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-sky-600 text-white shadow-sm shadow-sky-900/30 transition active:scale-95 disabled:bg-slate-300 disabled:text-slate-500 disabled:shadow-none dark:bg-sky-500 dark:disabled:bg-slate-800 dark:disabled:text-slate-600"
          // Keep focus in the textarea so the mobile keyboard doesn't close on send.
          onMouseDown={(e) => e.preventDefault()}
        >
          <Send className="size-[18px] -translate-x-px translate-y-px" />
        </button>
      </form>
      {showEmoji && (
        <div className="safe-bottom">
          <EmojiPicker onSelect={insertEmoji} />
        </div>
      )}
    </div>
  );
}
