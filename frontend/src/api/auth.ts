import { ApiError, apiRequest, setCsrfToken } from "./client";

export interface AuthUser {
  id: string;
  username: string;
  displayName: string;
}

interface SessionResponse {
  user: AuthUser;
  csrfToken: string;
  expiresAt: string;
}

/*
 * "Closing the tab signs you out": a marker in sessionStorage (wiped by the browser when the tab
 * closes, kept across refreshes) records that *this tab* signed in. A page load that finds a
 * valid session but no marker is a new tab or a reopened browser, so it signs out instead.
 * The marker is not a secret; the session itself stays in the HttpOnly cookie.
 */
const TAB_KEY = "duo:signed-in-tab";

function markTabSignedIn(): void {
  try {
    sessionStorage.setItem(TAB_KEY, "1");
  } catch {
    // Storage unavailable (private mode quirks): the app still works, just without this check.
  }
}

function clearTabSignedIn(): void {
  try {
    sessionStorage.removeItem(TAB_KEY);
  } catch {
    // ignore
  }
}

/** True if this tab signed in earlier (survives refresh, not tab or browser close). */
export function isTabSignedIn(): boolean {
  try {
    return sessionStorage.getItem(TAB_KEY) === "1";
  } catch {
    return true; // can't tell; don't force a sign-out
  }
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const session = await apiRequest<SessionResponse>("POST", "/auth/login", { username, password });
  setCsrfToken(session.csrfToken);
  markTabSignedIn();
  return session.user;
}

/** Restores the current session from the cookie. Resolves to null when signed out or expired. */
export async function fetchSession(): Promise<AuthUser | null> {
  try {
    const session = await apiRequest<SessionResponse>("GET", "/auth/me");
    setCsrfToken(session.csrfToken);
    return session.user;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw err;
  }
}

export async function logout(): Promise<void> {
  clearTabSignedIn();
  try {
    await apiRequest<void>("POST", "/auth/logout");
  } finally {
    setCsrfToken(null);
  }
}

export function describeLoginError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Incorrect username or password.";
    if (err.status === 429) return "Too many attempts. Please wait a few minutes and try again.";
    if (err.status === 0) return "Can't reach the server. Check your connection and try again.";
  }
  return "Something went wrong. Please try again.";
}
