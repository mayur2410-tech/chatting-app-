import type { ClientEvent, ServerEvent } from "./protocol";

export type SocketStatus = "connecting" | "open" | "closed";

interface ChatSocketHandlers {
  onEvent: (event: ServerEvent) => void;
  /** Fired on every successful (re)connection; the caller should catch up and flush its outbox. */
  onOpen: () => void;
  onStatus: (status: SocketStatus) => void;
  /** A connection attempt failed before opening (network down, or the session is no longer valid). */
  onConnectFailed: () => void;
  /** The server closed the socket because the session ended. No reconnection is attempted. */
  onSessionEnded: () => void;
}

const PING_INTERVAL_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
const MAX_BACKOFF_MS = 30_000;
const CLOSE_SESSION_ENDED = 4401;
const CLOSE_FORBIDDEN = 4403;
const CLOSE_PONG_TIMEOUT = 4000;

/**
 * Authenticated chat WebSocket with automatic reconnection (exponential backoff with jitter),
 * heartbeat-based dead-connection detection, and immediate retry when the device comes back online.
 * The session cookie authenticates the handshake; nothing secret is passed in the URL.
 */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private stopped = true;
  private attempt = 0;
  private retryTimer: number | undefined;
  private pingTimer: number | undefined;
  private pongTimer: number | undefined;

  constructor(private readonly handlers: ChatSocketHandlers) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    window.addEventListener("online", this.reconnectNow);
    document.addEventListener("visibilitychange", this.reconnectNow);
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    window.removeEventListener("online", this.reconnectNow);
    document.removeEventListener("visibilitychange", this.reconnectNow);
    window.clearTimeout(this.retryTimer);
    this.stopHeartbeat();
    const ws = this.ws;
    this.ws = null;
    ws?.close(1000);
    this.handlers.onStatus("closed");
  }

  /** Returns false if the socket is not open; the caller keeps the event queued. */
  send(event: ClientEvent): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(event));
    return true;
  }

  private reconnectNow = () => {
    if (this.stopped || document.visibilityState !== "visible" || this.ws) return;
    window.clearTimeout(this.retryTimer);
    this.attempt = 0;
    this.connect();
  };

  private connect(): void {
    window.clearTimeout(this.retryTimer);
    this.handlers.onStatus("connecting");
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${scheme}//${window.location.host}/api/ws/chat`);
    this.ws = ws;
    let opened = false;

    ws.onopen = () => {
      opened = true;
      this.attempt = 0;
      this.handlers.onStatus("open");
      this.startHeartbeat();
      this.handlers.onOpen();
    };

    ws.onmessage = (e: MessageEvent) => {
      if (typeof e.data !== "string") return;
      let event: ServerEvent;
      try {
        event = JSON.parse(e.data) as ServerEvent;
      } catch {
        return;
      }
      if (event.type === "pong") {
        window.clearTimeout(this.pongTimer);
        return;
      }
      this.handlers.onEvent(event);
    };

    ws.onclose = (e: CloseEvent) => {
      if (this.ws !== ws) return; // superseded or stopped
      this.ws = null;
      this.stopHeartbeat();
      if (this.stopped) return;
      this.handlers.onStatus("closed");
      if (e.code === CLOSE_SESSION_ENDED || e.code === CLOSE_FORBIDDEN) {
        this.stopped = true;
        this.handlers.onSessionEnded();
        return;
      }
      if (!opened) this.handlers.onConnectFailed();
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    this.attempt += 1;
    const delay = base / 2 + Math.random() * (base / 2);
    this.retryTimer = window.setTimeout(() => this.connect(), delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = window.setInterval(() => {
      if (!this.send({ type: "ping" })) return;
      window.clearTimeout(this.pongTimer);
      this.pongTimer = window.setTimeout(() => this.ws?.close(CLOSE_PONG_TIMEOUT, "heartbeat timeout"), PONG_TIMEOUT_MS);
    }, PING_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    window.clearInterval(this.pingTimer);
    window.clearTimeout(this.pongTimer);
  }
}
