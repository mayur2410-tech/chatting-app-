"""
In-memory registry of open chat WebSockets.

This works because the app runs as a single process. With multiple workers or hosts, events
published in one process would not reach sockets held by another; that setup needs a shared
event bus (e.g. Redis Pub/Sub or Postgres LISTEN/NOTIFY) feeding each process's manager.
"""

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.messaging.schemas import ev_error

CLOSE_SESSION_ENDED = 4401
CLOSE_FORBIDDEN = 4403


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    session_id: uuid.UUID
    conversation_id: uuid.UUID
    closed: bool = False
    # Presence: the tab reports whether the chat is visible ("active") or in the background.
    active: bool = True
    # Typing indicator state and when it was last relayed (throttling).
    typing: bool = False
    typing_relayed_at: float = 0.0
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, payload: dict[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            async with self._send_lock:
                await self.websocket.send_json(payload)
            return True
        except Exception:  # socket already gone; the receive loop will clean up
            self.closed = True
            return False

    async def close(self, code: int) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.websocket.close(code=code)
        except Exception:
            pass


class ConnectionManager:
    def __init__(self) -> None:
        self._by_conversation: dict[uuid.UUID, set[Connection]] = defaultdict(set)

    def add(self, conn: Connection) -> None:
        self._by_conversation[conn.conversation_id].add(conn)

    def remove(self, conn: Connection) -> None:
        conns = self._by_conversation.get(conn.conversation_id)
        if conns is not None:
            conns.discard(conn)
            if not conns:
                del self._by_conversation[conn.conversation_id]

    def connections(self, conversation_id: uuid.UUID) -> list[Connection]:
        return list(self._by_conversation.get(conversation_id, ()))

    async def broadcast(
        self, conversation_id: uuid.UUID, payload: dict[str, Any], *, exclude: Connection | None = None
    ) -> None:
        targets = [c for c in self.connections(conversation_id) if c is not exclude]
        if targets:
            await asyncio.gather(*(c.send(payload) for c in targets))

    def is_online(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Online = at least one of the user's open tabs has the chat visible."""
        return any(
            c.user_id == user_id and c.active and not c.closed for c in self.connections(conversation_id)
        )

    async def send_to_others(self, conversation_id: uuid.UUID, user_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """Send to everyone in the conversation except this user's own tabs."""
        targets = [c for c in self.connections(conversation_id) if c.user_id != user_id]
        if targets:
            await asyncio.gather(*(c.send(payload) for c in targets))

    async def send_to_user(self, conversation_id: uuid.UUID, user_id: uuid.UUID, payload: dict[str, Any]) -> None:
        targets = [c for c in self.connections(conversation_id) if c.user_id == user_id]
        if targets:
            await asyncio.gather(*(c.send(payload) for c in targets))

    async def end_session(self, session_id: uuid.UUID) -> None:
        """Disconnect every socket opened with this session (logout, revocation)."""
        targets = [c for conns in self._by_conversation.values() for c in conns if c.session_id == session_id]
        for conn in targets:
            await conn.send(ev_error("session_expired", "Session ended"))
            await conn.close(CLOSE_SESSION_ENDED)

    def count(self) -> int:
        return sum(len(c) for c in self._by_conversation.values())


manager = ConnectionManager()
