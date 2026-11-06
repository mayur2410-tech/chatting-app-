"""
WS /api/ws/chat — authenticated real-time channel. Protocol: docs/websocket-protocol.md.

Security model:
  * Origin must be in ALLOWED_ORIGINS (blocks cross-site WebSocket hijacking; this is the CSRF
    defence for the socket). Checked before the handshake is accepted.
  * The session cookie is validated before accepting; failures are refused with HTTP 403.
  * Identity comes only from the session. Events cannot carry a sender id (extra fields are rejected).
  * A watchdog re-validates the session every WS_AUTH_RECHECK_SECONDS and closes with 4401 once it
    is expired/revoked; logout closes the session's sockets immediately.
  * Message bodies are never logged.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, WebSocket
from sqlalchemy import update
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth.service import get_valid_session, utcnow
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.messaging import service
from app.messaging.connections import CLOSE_SESSION_ENDED, Connection, manager
from app.models import User
from app.messaging.schemas import (
    EV_PONG,
    MAX_FRAME_CHARS,
    DeliveredEvent,
    MessageOut,
    PingEvent,
    PresenceEvent,
    SendEvent,
    TypingEvent,
    client_event_adapter,
    ev_ack,
    ev_delivered,
    ev_error,
    ev_new,
    ev_presence,
    ev_typing,
)
from app.rate_limit import message_limiter

logger = logging.getLogger("duo.ws")

router = APIRouter()

CLOSE_POLICY = 1008
CLOSE_UNSUPPORTED_DATA = 1003
# While typing, the indicator is re-sent at most this often (clients expire it after ~6 s).
TYPING_RELAY_INTERVAL = 2.0


@dataclass(frozen=True)
class _Context:
    session_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID


def _authorize(token: str | None, settings: Settings) -> _Context | None:
    if not token or len(token) > 128:
        return None
    with get_sessionmaker()() as db:
        session = get_valid_session(db, token, settings)
        if session is None:
            return None
        conversation = service.get_user_conversation(db, session.user_id)
        if conversation is None:
            return None
        return _Context(session.id, session.user_id, conversation.id)


def _still_authorized(token: str, settings: Settings, ctx: _Context) -> bool:
    with get_sessionmaker()() as db:
        session = get_valid_session(db, token, settings)
        return (
            session is not None
            and session.id == ctx.session_id
            and service.is_member(db, ctx.conversation_id, ctx.user_id)
        )


class _InvalidReply(Exception):
    pass


def _store(new: service.NewMessage):  # type: ignore[no-untyped-def]
    """Store idempotently. A reply must target a live message in the same conversation
    (checked only for new messages, so a retry of a stored message is always acked)."""
    with get_sessionmaker()() as db:
        if new.reply_to_id is not None and service.find_by_client_id(db, new.sender_id, new.client_message_id) is None:
            if not service.is_valid_reply_target(db, new.conversation_id, new.reply_to_id):
                raise _InvalidReply
        message, created = service.store_message(db, new)
        return MessageOut.of(message), created


def _touch_last_seen(user_id: uuid.UUID) -> datetime:
    with get_sessionmaker()() as db:
        now = utcnow()
        db.execute(update(User).where(User.id == user_id).values(last_seen_at=now))
        db.commit()
        return now


async def _after_presence_change(conn: Connection, was_online: bool) -> None:
    """If the user's online state flipped, record last-seen and tell the partner."""
    online = manager.is_online(conn.conversation_id, conn.user_id)
    if online == was_online:
        return
    last_seen = await run_in_threadpool(_touch_last_seen, conn.user_id)
    await manager.send_to_others(conn.conversation_id, conn.user_id, ev_presence(conn.user_id, online, last_seen))


_background: set[asyncio.Task[None]] = set()


def _spawn(coro) -> None:  # type: ignore[no-untyped-def]
    """Start a fire-and-forget task, keeping a reference so it isn't garbage-collected mid-run."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _announce_departure(conn: Connection, was_online: bool) -> None:
    try:
        if conn.typing:
            await manager.send_to_others(conn.conversation_id, conn.user_id, ev_typing(conn.user_id, False))
        await _after_presence_change(conn, was_online)
    except Exception:
        logger.exception("Presence update on disconnect failed")


def _mark_delivered(conversation_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID]):  # type: ignore[no-untyped-def]
    with get_sessionmaker()() as db:
        return service.mark_delivered(db, conversation_id, user_id, ids)


@router.websocket("/api/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    settings = get_settings()

    if websocket.headers.get("origin") not in settings.allowed_origins:
        await websocket.close(code=CLOSE_POLICY)  # before accept → handshake refused (403)
        return

    token = websocket.cookies.get(settings.session_cookie_name)
    ctx = await run_in_threadpool(_authorize, token, settings)
    if ctx is None:
        await websocket.close(code=CLOSE_POLICY)
        return

    await websocket.accept()
    conn = Connection(websocket, ctx.user_id, ctx.session_id, ctx.conversation_id)
    was_online = manager.is_online(ctx.conversation_id, ctx.user_id)
    manager.add(conn)
    watchdog = asyncio.create_task(_watch_session(conn, token or "", settings, ctx))
    try:
        await _after_presence_change(conn, was_online)
        await _receive_loop(conn, settings)
    finally:
        watchdog.cancel()
        was_online = manager.is_online(ctx.conversation_id, ctx.user_id)
        manager.remove(conn)
        conn.closed = True
        # Run as its own task: this handler may be cancelled as the socket goes away, and the
        # partner must still learn "stopped typing" / "last seen".
        _spawn(_announce_departure(conn, was_online))


async def _watch_session(conn: Connection, token: str, settings: Settings, ctx: _Context) -> None:
    while not conn.closed:
        await asyncio.sleep(settings.ws_auth_recheck_seconds)
        try:
            valid = await run_in_threadpool(_still_authorized, token, settings, ctx)
        except Exception:
            logger.exception("Session re-check failed")
            continue
        if not valid:
            await conn.send(ev_error("session_expired", "Session ended"))
            await conn.close(CLOSE_SESSION_ENDED)
            return


async def _receive_loop(conn: Connection, settings: Settings) -> None:
    while not conn.closed:
        try:
            frame = await conn.websocket.receive()
        except RuntimeError:  # receive after close
            return
        if frame["type"] == "websocket.disconnect":
            return

        raw = frame.get("text")
        if raw is None:
            await conn.send(ev_error("unsupported_data", "Only text frames are accepted"))
            await conn.close(CLOSE_UNSUPPORTED_DATA)
            return
        if len(raw) > MAX_FRAME_CHARS:
            await conn.send(ev_error("payload_too_large", "Event too large"))
            continue

        try:
            event = client_event_adapter.validate_json(raw)
        except ValidationError as exc:
            code = "invalid_json" if any(e["type"] == "json_invalid" for e in exc.errors()) else "invalid_event"
            await conn.send(ev_error(code, "Malformed event"))
            continue

        try:
            if isinstance(event, SendEvent):
                await _handle_send(conn, event, settings)
            elif isinstance(event, DeliveredEvent):
                await _handle_delivered(conn, event)
            elif isinstance(event, TypingEvent):
                await _handle_typing(conn, event)
            elif isinstance(event, PresenceEvent):
                was_online = manager.is_online(conn.conversation_id, conn.user_id)
                conn.active = event.state == "active"
                await _after_presence_change(conn, was_online)
            elif isinstance(event, PingEvent):
                await conn.send(EV_PONG)
        except Exception:
            logger.exception("Error handling %s event", type(event).__name__)
            await conn.send(ev_error("internal_error", "Something went wrong"))


async def _handle_send(conn: Connection, event: SendEvent, settings: Settings) -> None:
    key = f"user:{conn.user_id}"
    retry_after = message_limiter.retry_after(key, settings.message_rate_limit, settings.message_rate_window_seconds)
    if retry_after:
        await conn.send(
            ev_error(
                "rate_limited",
                "Sending too fast",
                client_message_id=event.client_message_id,
                retry_after=retry_after,
            )
        )
        return

    try:
        message, created = await run_in_threadpool(
            _store,
            service.NewMessage(
                conversation_id=conn.conversation_id,
                sender_id=conn.user_id,  # never taken from the client
                client_message_id=event.client_message_id,
                body=event.body,
                reply_to_id=event.reply_to_id,
            ),
        )
    except _InvalidReply:
        await conn.send(
            ev_error("invalid_reply", "The message you replied to is not available", client_message_id=event.client_message_id)
        )
        return

    await conn.send(ev_ack(event.client_message_id, message))
    if created:
        message_limiter.record(key)
        # Everyone else in the conversation: the partner's tabs and the sender's other tabs.
        await manager.broadcast(conn.conversation_id, ev_new(message), exclude=conn)


async def _handle_delivered(conn: Connection, event: DeliveredEvent) -> None:
    marked = await run_in_threadpool(_mark_delivered, conn.conversation_id, conn.user_id, list(event.message_ids))
    for message_id, delivered_at in marked:
        await manager.broadcast(conn.conversation_id, ev_delivered(message_id, delivered_at))


async def _handle_typing(conn: Connection, event: TypingEvent) -> None:
    """Relay to the partner on change, and while typing at most every TYPING_RELAY_INTERVAL."""
    now = time.monotonic()
    changed = event.is_typing != conn.typing
    if not changed and not (event.is_typing and now - conn.typing_relayed_at >= TYPING_RELAY_INTERVAL):
        return
    conn.typing = event.is_typing
    conn.typing_relayed_at = now
    await manager.send_to_others(conn.conversation_id, conn.user_id, ev_typing(conn.user_id, event.is_typing))
