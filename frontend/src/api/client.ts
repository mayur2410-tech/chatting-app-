/**
 * Minimal JSON client for the Duo API. The session lives in an HttpOnly cookie the browser
 * attaches automatically; the CSRF token is held only in this module's memory.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Network error");
  }

  if (!response.ok) {
    const retryAfter = Number(response.headers.get("Retry-After")) || undefined;
    throw new ApiError(response.status, `Request failed (${response.status})`, retryAfter);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
