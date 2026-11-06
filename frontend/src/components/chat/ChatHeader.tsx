import { useEffect, useRef, useState } from "react";
import { Eraser, Eye, EyeOff, Loader2, LogOut, MoreVertical, Plane, WifiOff } from "lucide-react";
import { formatLastSeen } from "../../lib/format";
import type { SocketStatus } from "../../messaging/socket";
import type { PartnerStatus } from "../../messaging/useConversation";
import type { Participant } from "../../types";
import { IconButton } from "../ui";

interface ChatHeaderProps {
  partner: Participant;
  connection: SocketStatus;
  partnerStatus: PartnerStatus;
  revealedCount: number;
  totalCount: number;
  onRevealAll: () => void;
  onHideAll: () => void;
  onClearChat: () => void;
  onSignOut: () => void;
}

/** Re-render periodically so "last seen today" becomes "yesterday" at midnight. */
function useMinuteTick(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

/**
 * The line under the partner's name. Our own connection problems take priority, then "online" or
 * "last seen …" (IST, 12-hour). "typing…" is shown above the message box instead.
 */
function StatusLine({ connection, partnerStatus }: { connection: SocketStatus; partnerStatus: PartnerStatus }) {
  const now = useMinuteTick();
  if (connection === "connecting") {
    return (
      <>
        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
        Connecting…
      </>
    );
  }
  if (connection === "closed") {
    return (
      <>
        <WifiOff className="size-3.5" aria-hidden="true" />
        Offline · reconnecting
      </>
    );
  }
  if (partnerStatus.online) {
    return (
      <>
        <span className="size-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px] shadow-emerald-400" aria-hidden="true" />
        online
      </>
    );
  }
  if (partnerStatus.lastSeenAt) return <>{formatLastSeen(partnerStatus.lastSeenAt, now)}</>;
  return <>offline</>;
}

function HeaderMenu({ onClearChat, onSignOut }: Pick<ChatHeaderProps, "onClearChat" | "onSignOut">) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent | TouchEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item =
    "flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-slate-700 transition hover:bg-sky-50 dark:text-slate-200 dark:hover:bg-slate-800";

  return (
    <div ref={rootRef} className="relative">
      <IconButton
        onClick={() => setOpen((o) => !o)}
        aria-label="Menu"
        aria-haspopup="menu"
        aria-expanded={open}
        className="text-sky-100 hover:bg-white/10"
      >
        <MoreVertical className="size-5" />
      </IconButton>
      {open && (
        <div
          role="menu"
          className="animate-fade-up absolute right-0 top-11 z-30 w-48 overflow-hidden rounded-xl bg-white py-1 shadow-xl ring-1 ring-slate-900/10 dark:bg-slate-900 dark:ring-white/10"
        >
          <button
            type="button"
            role="menuitem"
            className={item}
            onClick={() => {
              setOpen(false);
              onClearChat();
            }}
          >
            <Eraser className="size-4 text-slate-400" aria-hidden="true" />
            Clear chat
          </button>
          <button
            type="button"
            role="menuitem"
            className={item}
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            <LogOut className="size-4 text-slate-400" aria-hidden="true" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/** Cockpit-style header: who you're talking to, connection status, and quick privacy controls. */
export function ChatHeader({
  partner,
  connection,
  partnerStatus,
  revealedCount,
  totalCount,
  onRevealAll,
  onHideAll,
  onClearChat,
  onSignOut,
}: ChatHeaderProps) {
  const allRevealed = totalCount > 0 && revealedCount >= totalCount;
  const toolbarBtn =
    "inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium text-sky-100 transition hover:bg-white/10 active:scale-95 disabled:opacity-40";

  return (
    <header className="safe-top relative z-20 shrink-0 bg-sky-950 text-sky-50 shadow-md shadow-sky-950/30">
      <div className="flex items-center gap-3 px-3 py-2">
        <div className="relative shrink-0">
          <div
            className="flex size-10 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-sky-600 text-sm font-bold text-white ring-2 ring-sky-300/30"
            aria-hidden="true"
          >
            {partner.displayName.slice(0, 1).toUpperCase()}
          </div>
          <span className="absolute -bottom-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full bg-sky-950">
            <Plane className="size-2.5 text-amber-300" aria-hidden="true" />
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold leading-tight">{partner.displayName}</p>
          <p className="flex items-center gap-1.5 text-xs text-sky-300" aria-live="polite">
            <StatusLine connection={connection} partnerStatus={partnerStatus} />
          </p>
        </div>
        <HeaderMenu onClearChat={onClearChat} onSignOut={onSignOut} />
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-white/10 px-3 py-1">
        <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-amber-300/90" aria-live="polite">
          {revealedCount === 0 ? "All hidden" : `${revealedCount} revealed`}
        </p>
        <div className="flex items-center gap-1">
          <button type="button" onClick={onRevealAll} disabled={allRevealed} className={toolbarBtn}>
            <Eye className="size-4" aria-hidden="true" />
            Reveal all
          </button>
          <button type="button" onClick={onHideAll} disabled={revealedCount === 0} className={toolbarBtn}>
            <EyeOff className="size-4" aria-hidden="true" />
            Hide all
          </button>
        </div>
      </div>
    </header>
  );
}
