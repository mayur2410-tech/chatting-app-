import { useCallback, useEffect, useState } from "react";
import { describeLoginError, fetchSession, isTabSignedIn, login, logout, type AuthUser } from "./api/auth";
import { PlaneLoader } from "./components/PlaneLoader";
import { SESSION_CHECK_INTERVAL_MS } from "./config";
import { useViewportHeight } from "./hooks/useViewportHeight";
import { useConversation } from "./messaging/useConversation";
import { ChatScreen } from "./screens/ChatScreen";
import { LoginScreen } from "./screens/LoginScreen";
import type { Screen } from "./types";

const SESSION_EXPIRED = "Your session has ended. Please sign in again.";
const SERVER_UNREACHABLE = "Can't reach the server right now. You can still try signing in.";

export default function App() {
  useViewportHeight();

  const [screen, setScreen] = useState<Screen>("restoring");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const startSession = useCallback((authUser: AuthUser) => {
    setUser(authUser);
    setNotice(null);
    setScreen("chat");
  }, []);

  /** Drops all client state (the conversation hook tears down its socket) and returns to sign-in. */
  const endSession = useCallback((message: string | null) => {
    setUser(null);
    setNotice(message);
    setScreen("login");
  }, []);

  // On page load: keep the session after a refresh, but a new tab or a reopened browser must sign
  // in again ("closing the tab signs you out").
  useEffect(() => {
    let cancelled = false;
    fetchSession()
      .then(async (authUser) => {
        if (cancelled) return;
        if (authUser && isTabSignedIn()) {
          startSession(authUser);
          return;
        }
        if (authUser) await logout().catch(() => undefined); // left over from a closed tab
        if (!cancelled) setScreen("login");
      })
      .catch(() => {
        if (cancelled) return;
        setNotice(SERVER_UNREACHABLE);
        setScreen("login");
      });
    return () => {
      cancelled = true;
    };
  }, [startSession]);

  /** Signs out locally if the server says the session is gone. */
  const verifySession = useCallback(async () => {
    try {
      if (!(await fetchSession())) endSession(SESSION_EXPIRED);
    } catch {
      // Network blip: keep the user where they are; the next check will retry.
    }
  }, [endSession]);

  const conversation = useConversation(user, () => void verifySession());

  // While signed in, re-check the session periodically and whenever the tab becomes visible.
  const signedIn = user !== null;
  useEffect(() => {
    if (!signedIn) return;
    const interval = window.setInterval(() => void verifySession(), SESSION_CHECK_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void verifySession();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [signedIn, verifySession]);

  const handleLogin = useCallback(
    async (username: string, password: string): Promise<string | null> => {
      try {
        startSession(await login(username, password));
        return null;
      } catch (err) {
        return describeLoginError(err);
      }
    },
    [startSession],
  );

  const handleSignOut = useCallback(async () => {
    // Leave the chat first: that stops the socket, so the server closing it during logout isn't
    // mistaken for an expired session ("Your session has ended").
    endSession(null);
    try {
      await logout();
    } catch {
      // The server session will still expire on its own; local state is already cleared.
    }
  }, [endSession]);

  if (screen === "restoring") {
    return (
      <div className="app-shell sky-gradient flex items-center justify-center" aria-busy="true">
        <PlaneLoader label="Preparing your flight…" size={96} />
      </div>
    );
  }

  if (screen === "login" || user === null) {
    return <LoginScreen onSubmit={handleLogin} notice={notice} />;
  }

  return (
    <ChatScreen
      me={{ id: user.id, displayName: user.displayName }}
      conversation={conversation}
      onSignOut={() => void handleSignOut()}
    />
  );
}
