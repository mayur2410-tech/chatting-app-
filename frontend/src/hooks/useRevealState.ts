import { useCallback, useEffect, useRef, useState } from "react";
import type { DecodeResult, RevealedEntry } from "../types";

/**
 * Holds the only readable copies of message text. Entries expire after `timeoutMs`,
 * and everything is dropped on Hide All, when the tab is backgrounded, or when the
 * owning component unmounts (e.g. on Lock).
 *
 * `decode` decrypts one message (by local id); null means the message no longer exists.
 * Failures are kept (as an error entry) so the bubble can say why it can't be read.
 */
export function useRevealState(timeoutMs: number, decode: (id: string) => Promise<DecodeResult | null>) {
  const [revealed, setRevealed] = useState<Map<string, RevealedEntry>>(() => new Map());
  const [pending, setPending] = useState<Set<string>>(() => new Set());
  // Bumped by hideAll so decryptions that finish afterwards are discarded.
  const generation = useRef(0);

  const reveal = useCallback(
    async (ids: string[]) => {
      if (ids.length === 0) return;
      const gen = generation.current;
      setPending((prev) => new Set([...prev, ...ids]));

      const results = await Promise.all(ids.map(async (id) => [id, await decode(id)] as const));

      setPending((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
      if (gen !== generation.current) return;

      const expiresAt = Date.now() + timeoutMs;
      setRevealed((prev) => {
        const next = new Map(prev);
        for (const [id, result] of results) {
          if (result === null) continue;
          next.set(id, result.ok ? { text: result.text, expiresAt } : { text: null, error: result.reason, expiresAt });
        }
        return next;
      });
    },
    [timeoutMs, decode],
  );

  const hide = useCallback((id: string) => {
    setRevealed((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Map(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const hideAll = useCallback(() => {
    generation.current += 1;
    setPending(new Set());
    setRevealed(new Map());
  }, []);

  // Expire entries when their reveal window ends.
  useEffect(() => {
    if (revealed.size === 0) return;
    let soonest = Infinity;
    revealed.forEach((entry) => {
      soonest = Math.min(soonest, entry.expiresAt);
    });
    const timer = window.setTimeout(() => {
      const now = Date.now();
      setRevealed((prev) => {
        const next = new Map<string, RevealedEntry>();
        prev.forEach((entry, id) => {
          if (entry.expiresAt > now) next.set(id, entry);
        });
        return next;
      });
    }, Math.max(0, soonest - Date.now()) + 20);
    return () => window.clearTimeout(timer);
  }, [revealed]);

  // Hide everything as soon as the page is backgrounded or being unloaded.
  useEffect(() => {
    const onHidden = () => {
      if (document.visibilityState === "hidden") hideAll();
    };
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("pagehide", hideAll);
    return () => {
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("pagehide", hideAll);
    };
  }, [hideAll]);

  return { revealed, pending, reveal, hide, hideAll };
}
