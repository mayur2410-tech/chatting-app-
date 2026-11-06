"""
Phase 3 messaging: HTTP history/deletion endpoints and the /api/ws/chat protocol.

All sockets share one TestClient (one event loop) so server-side broadcasts between connections
work as they do in production. Each user's identity is passed as an explicit Cookie header.
"""

import uuid
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.auth.service import utcnow
from app.config import get_settings
from app.messaging.connections import manager
from app.messaging.schemas import MAX_BODY_CHARS
from app.models import AuthSession, Message
from app.security import hash_token
from app.users import create_user, set_active
from tests.conftest import FRONTEND_ORIGIN, PASSWORDS, login

COOKIE = "duo_session"
WS_URL = "/api/ws/chat"


class Identity:
    def __init__(self, user, token: str, csrf: str) -> None:
        self.user = user
        self.token = token
        self.csrf = csrf

    @property
    def id(self) -> str:
        return str(self.user.id)

    def headers(self, *, csrf: bool = False) -> dict[str, str]:
        h = {"Cookie": f"{COOKIE}={self.token}"}
        if csrf:
            h["X-CSRF-Token"] = self.csrf
        return h


def sign_in(app, user, password: str) -> Identity:
    c = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    r = login(c, user.username, password)
    assert r.status_code == 200
    return Identity(user, c.cookies.get(COOKIE), r.json()["csrfToken"])


@pytest.fixture
def hub(app):
    """Cookie-less client shared by every socket and request in a test."""
    with TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN}) as c:
        yield c


@pytest.fixture
def alice(app, users) -> Identity:
    return sign_in(app, users["alex"], PASSWORDS["alex"])


@pytest.fixture
def bob(app, users) -> Identity:
    return sign_in(app, users["sam"], PASSWORDS["sam"])


class _QuietSocket:
    """Test socket that skips live presence/typing events, so tests can read the frames they expect."""

    IGNORED = {"presence", "typing"}

    def __init__(self, ws) -> None:
        self._ws = ws

    def receive_json(self):
        while True:
            event = self._ws.receive_json()
            if not (isinstance(event, dict) and event.get("type") in self.IGNORED):
                return event

    def __getattr__(self, name):
        return getattr(self._ws, name)


@contextmanager
def connect(
    hub: TestClient, who: Identity | None = None, origin: str | None = FRONTEND_ORIGIN, *, raw: bool = False
):
    """Open the chat socket as `who`. raw=True keeps presence/typing events in the stream."""
    headers = who.headers() if who else {}
    if origin is not None:
        headers["Origin"] = origin
    with hub.websocket_connect(WS_URL, headers=headers) as ws:
        yield ws if raw else _QuietSocket(ws)


def send(ws, text: str = "synthetic test message", cid: str | None = None, **extra) -> str:
    cid = cid or str(uuid.uuid4())
    ws.send_json(
        {
            "type": "message.send",
            "clientMessageId": cid,
            "body": text,
            **extra,
        }
    )
    return cid


def until(ws, event_type: str) -> dict:
    """Read frames until one of the given type arrives (skipping broadcasts from other users)."""
    for _ in range(20):
        event = ws.receive_json()
        if event["type"] == event_type:
            return event
    raise AssertionError(f"no {event_type} event received")


def conversation_id(hub: TestClient, who: Identity) -> str:
    r = hub.get("/api/conversations", headers=who.headers())
    assert r.status_code == 200
    return r.json()["conversations"][0]["id"]


def history(hub: TestClient, who: Identity, **params) -> dict:
    r = hub.get(f"/api/conversations/{conversation_id(hub, who)}/messages", params=params, headers=who.headers())
    assert r.status_code == 200, r.text
    return r.json()


# --- conversations ----------------------------------------------------------


def test_single_shared_conversation_is_created_for_the_two_users(hub, alice, bob):
    a = hub.get("/api/conversations", headers=alice.headers()).json()
    b = hub.get("/api/conversations", headers=bob.headers()).json()
    assert len(a["conversations"]) == len(b["conversations"]) == 1
    assert a["conversations"][0]["id"] == b["conversations"][0]["id"]
    members = {m["id"]: m["displayName"] for m in a["conversations"][0]["members"]}
    assert members == {alice.id: "Alex", bob.id: "Sam"}
    assert "password" not in str(a).lower()
    assert a["maxBodyChars"] == MAX_BODY_CHARS


def test_conversation_endpoints_require_auth(hub, alice):
    cid = conversation_id(hub, alice)
    assert hub.get("/api/conversations").status_code == 401
    assert hub.get(f"/api/conversations/{cid}/messages").status_code == 401
    assert hub.delete(f"/api/messages/{uuid.uuid4()}").status_code == 401


# --- WebSocket handshake ----------------------------------------------------


def test_ws_rejects_unauthenticated(hub, users):
    with pytest.raises(WebSocketDisconnect):
        with connect(hub, None):
            pass


def test_ws_rejects_forged_cookie(hub, users):
    with pytest.raises(WebSocketDisconnect):
        with hub.websocket_connect(WS_URL, headers={"Origin": FRONTEND_ORIGIN, "Cookie": f"{COOKIE}=forged"}):
            pass


@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_ws_rejects_bad_origin(hub, alice, origin):
    with pytest.raises(WebSocketDisconnect):
        with connect(hub, alice, origin=origin):
            pass


def test_ws_rejects_missing_origin(app, alice):
    bare = TestClient(app, base_url="http://localhost")  # no default Origin header
    with pytest.raises(WebSocketDisconnect):
        with bare.websocket_connect(WS_URL, headers=alice.headers()):
            pass


def test_ws_rejects_revoked_and_expired_sessions(hub, alice, bob, db):
    db.execute(
        AuthSession.__table__.update()
        .where(AuthSession.token_hash == hash_token(alice.token))
        .values(revoked_at=utcnow())
    )
    db.execute(
        AuthSession.__table__.update()
        .where(AuthSession.token_hash == hash_token(bob.token))
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    for who in (alice, bob):
        with pytest.raises(WebSocketDisconnect):
            with connect(hub, who):
                pass


def test_non_member_cannot_connect_or_read(app, hub, alice, bob, db, users):
    cid = conversation_id(hub, alice)  # conversation now exists between alex and sam
    set_active(db, get_settings(), "sam", False)
    outsider = create_user(db, get_settings(), "mallory", "Mallory", "a long outsider password")
    eve = sign_in(app, outsider, "a long outsider password")

    assert hub.get("/api/conversations", headers=eve.headers()).json()["conversations"] == []
    assert hub.get(f"/api/conversations/{cid}/messages", headers=eve.headers()).status_code == 404
    assert hub.get(f"/api/conversations/{uuid.uuid4()}/messages", headers=alice.headers()).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with connect(hub, eve):
            pass


# --- sending & receiving ----------------------------------------------------


def test_send_and_receive_between_users(hub, alice, bob, db):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        cid = send(a, "Synthetic hello from A")
        ack = a.receive_json()
        assert ack["type"] == "message.ack"
        assert ack["clientMessageId"] == cid
        msg = ack["message"]
        assert msg["senderId"] == alice.id
        assert msg["body"] == "Synthetic hello from A"
        assert msg["replyToId"] is None
        assert msg["deliveredAt"] is None

        new = b.receive_json()
        assert new == {"type": "message.new", "message": msg}

        # B replies
        send(b, "Synthetic reply from B")
        assert b.receive_json()["type"] == "message.ack"
        reply = a.receive_json()
        assert reply["type"] == "message.new"
        assert reply["message"]["senderId"] == bob.id

    stored = db.scalars(select(Message).order_by(Message.seq)).all()
    assert [m.body for m in stored] == ["Synthetic hello from A", "Synthetic reply from B"]
    assert [str(m.sender_id) for m in stored] == [alice.id, bob.id]


def test_client_cannot_choose_sender(hub, alice, bob, db):
    with connect(hub, alice) as a:
        send(a, "spoof attempt", senderId=bob.id)
        err = a.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_event"
    assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_emoji_and_unicode_round_trip(hub, alice, bob):
    text = "Test 😀👍🏽 ❤️ 🇮🇳 — नमस्ते — 你好 — مرحبا — 𝔘𝔫𝔦𝔠𝔬𝔡𝔢\nsecond line"
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, text)
        assert a.receive_json()["message"]["body"] == text
        assert b.receive_json()["message"]["body"] == text
    assert history(hub, bob)["messages"][0]["body"] == text


def test_messages_persist_in_order(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        for i in range(5):
            sender = a if i % 2 == 0 else b
            send(sender, f"synthetic {i}")
            until(sender, "message.ack")  # stored before the next one is sent
    page = history(hub, alice)
    assert [m["body"] for m in page["messages"]] == [f"synthetic {i}" for i in range(5)]
    seqs = [m["seq"] for m in page["messages"]]
    assert seqs == sorted(seqs)
    assert page["hasMore"] is False


def test_duplicate_client_message_id_is_idempotent(hub, alice, bob, db):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        cid = send(a, "only once")
        first = a.receive_json()["message"]
        assert b.receive_json()["type"] == "message.new"

        send(a, "only once", cid=cid)  # retry, e.g. after a dropped ack
        second = a.receive_json()
        assert second["type"] == "message.ack"
        assert second["message"]["id"] == first["id"]

        a.send_json({"type": "ping"})
        b.send_json({"type": "ping"})
        assert a.receive_json() == {"type": "pong"}
        assert b.receive_json() == {"type": "pong"}  # no second message.new before the pong

    assert db.scalar(select(func.count()).select_from(Message)) == 1


def test_same_client_id_from_different_users_does_not_collide(hub, alice, bob, db):
    shared = str(uuid.uuid4())
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, "from a", cid=shared)
        a.receive_json()
        b.receive_json()
        send(b, "from b", cid=shared)
        assert b.receive_json()["message"]["body"] == "from b"
    assert db.scalar(select(func.count()).select_from(Message)) == 2


def test_multiple_tabs_receive_events(hub, alice, bob):
    with connect(hub, alice) as a1, connect(hub, alice) as a2, connect(hub, bob) as b1, connect(hub, bob) as b2:
        send(a1, "to every tab")
        ack = a1.receive_json()
        for ws in (a2, b1, b2):
            event = ws.receive_json()
            assert event["type"] == "message.new"
            assert event["message"]["id"] == ack["message"]["id"]


def test_reconnect_recovers_missed_messages(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, "seen live")
        a.receive_json()
        last_seen = b.receive_json()["message"]["seq"]

    # Bob is offline; Alice keeps sending.
    with connect(hub, alice) as a:
        for text in ("missed 1", "missed 2"):
            send(a, text)
            a.receive_json()

    caught_up = history(hub, bob, after=last_seen)
    assert [m["body"] for m in caught_up["messages"]] == ["missed 1", "missed 2"]
    assert caught_up["hasMore"] is False


def test_pagination_cursor_is_stable(hub, alice):
    with connect(hub, alice) as a:
        for i in range(7):
            send(a, f"m{i}")
            a.receive_json()

    latest = history(hub, alice, limit=3)
    assert [m["body"] for m in latest["messages"]] == ["m4", "m5", "m6"]
    assert latest["hasMore"] is True

    older = history(hub, alice, limit=3, before=latest["messages"][0]["seq"])
    assert [m["body"] for m in older["messages"]] == ["m1", "m2", "m3"]
    oldest = history(hub, alice, limit=3, before=older["messages"][0]["seq"])
    assert [m["body"] for m in oldest["messages"]] == ["m0"]
    assert oldest["hasMore"] is False

    newer = history(hub, alice, limit=3, after=older["messages"][-1]["seq"])
    assert [m["body"] for m in newer["messages"]] == ["m4", "m5", "m6"]

    cid = conversation_id(hub, alice)
    both = hub.get(f"/api/conversations/{cid}/messages?before=5&after=1", headers=alice.headers())
    assert both.status_code == 400


# --- delivery receipts ------------------------------------------------------


def test_delivery_receipts(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, "please confirm")
        msg = a.receive_json()["message"]
        b.receive_json()

        # The sender cannot mark its own message delivered.
        a.send_json({"type": "message.delivered", "messageIds": [msg["id"]]})
        a.send_json({"type": "ping"})
        assert a.receive_json() == {"type": "pong"}

        b.send_json({"type": "message.delivered", "messageIds": [msg["id"]]})
        receipt = a.receive_json()
        assert receipt["type"] == "message.delivered"
        assert receipt["messageId"] == msg["id"]
        assert b.receive_json()["type"] == "message.delivered"

    assert history(hub, alice)["messages"][0]["deliveredAt"] is not None


# --- deletion ---------------------------------------------------------------


def test_sender_deletes_for_both_users(hub, alice, bob, db):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, "delete me")
        msg = a.receive_json()["message"]
        b.receive_json()
        before = utcnow() - timedelta(minutes=1)

        r = hub.delete(f"/api/messages/{msg['id']}", headers=alice.headers(csrf=True))
        assert r.status_code == 204
        for ws in (a, b):
            event = ws.receive_json()
            assert event == {
                "type": "message.deleted",
                "messageId": msg["id"],
                "senderId": alice.id,
                "clientMessageId": msg["clientMessageId"],
            }

    assert history(hub, bob)["messages"] == []
    row = db.get(Message, uuid.UUID(msg["id"]))
    db.refresh(row)
    assert row.deleted_at is not None
    assert row.body == ""  # payload wiped, only a tombstone remains

    cid = conversation_id(hub, bob)
    dels = hub.get(
        f"/api/conversations/{cid}/deletions", params={"since": before.isoformat()}, headers=bob.headers()
    ).json()
    assert [d["id"] for d in dels["deleted"]] == [msg["id"]]

    # Idempotent
    assert hub.delete(f"/api/messages/{msg['id']}", headers=alice.headers(csrf=True)).status_code == 204


def test_delete_authorization(hub, alice, bob):
    with connect(hub, alice) as a:
        send(a, "alice's message")
        msg_id = a.receive_json()["message"]["id"]

    assert hub.delete(f"/api/messages/{msg_id}", headers=bob.headers(csrf=True)).status_code == 403
    assert hub.delete(f"/api/messages/{msg_id}", headers=alice.headers()).status_code == 403  # no CSRF
    assert hub.delete(f"/api/messages/{msg_id}", headers={**alice.headers(), "X-CSRF-Token": bob.csrf}).status_code == 403
    assert hub.delete(f"/api/messages/{uuid.uuid4()}", headers=alice.headers(csrf=True)).status_code == 404
    assert len(history(hub, alice)["messages"]) == 1


# --- validation & limits ----------------------------------------------------


def test_message_size_limits(hub, alice, db):
    with connect(hub, alice) as a:
        send(a, "x" * (MAX_BODY_CHARS + 1))
        assert a.receive_json()["code"] == "invalid_event"

        send(a, "")
        assert a.receive_json()["code"] == "invalid_event"

        a.send_text("y" * 70_000)
        assert a.receive_json()["code"] == "payload_too_large"

        send(a, "   ")
        assert a.receive_json()["code"] == "invalid_event"

        send(a, "x" * MAX_BODY_CHARS)
        assert a.receive_json()["type"] == "message.ack"
    assert db.scalar(select(func.count()).select_from(Message)) == 1


def test_malformed_events_are_rejected(hub, alice):
    with connect(hub, alice) as a:
        a.send_text("{not json")
        assert a.receive_json()["code"] == "invalid_json"
        a.send_json({"type": "message.unknown"})
        assert a.receive_json()["code"] == "invalid_event"
        a.send_json({"type": "message.send", "clientMessageId": "not-a-uuid", "body": "x"})
        assert a.receive_json()["code"] == "invalid_event"
        send(a, "not a reply id", replyToId="nope")
        assert a.receive_json()["code"] == "invalid_event"
        # The socket stays usable.
        a.send_json({"type": "ping"})
        assert a.receive_json() == {"type": "pong"}


def test_binary_frames_close_the_socket(hub, alice):
    with connect(hub, alice) as a:
        a.send_bytes(b"\x00\x01")
        assert a.receive_json()["code"] == "unsupported_data"
        with pytest.raises(WebSocketDisconnect) as exc:
            a.receive_json()
        assert exc.value.code == 1003


def test_send_rate_limit(hub, alice):
    limit = get_settings().message_rate_limit
    with connect(hub, alice) as a:
        for i in range(limit):
            send(a, f"msg {i}")
            assert a.receive_json()["type"] == "message.ack"
        cid = send(a, "one too many")
        err = a.receive_json()
        assert err["code"] == "rate_limited"
        assert err["clientMessageId"] == cid
        assert err["retryAfter"] > 0


def test_revoked_session_is_disconnected(hub, alice, db):
    with connect(hub, alice) as a:
        db.execute(
            AuthSession.__table__.update()
            .where(AuthSession.token_hash == hash_token(alice.token))
            .values(revoked_at=utcnow())
        )
        db.commit()
        assert a.receive_json() == {"type": "error", "code": "session_expired", "message": "Session ended"}
        with pytest.raises(WebSocketDisconnect) as exc:
            a.receive_json()
        assert exc.value.code == 4401


def test_expired_session_is_disconnected(hub, alice, db):
    with connect(hub, alice) as a:
        db.execute(
            AuthSession.__table__.update()
            .where(AuthSession.token_hash == hash_token(alice.token))
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        db.commit()
        assert a.receive_json()["code"] == "session_expired"
        with pytest.raises(WebSocketDisconnect):
            a.receive_json()


def test_logout_closes_that_sessions_sockets_immediately(app, hub, alice, users):
    other_tab_session = sign_in(app, users["alex"], PASSWORDS["alex"])
    with connect(hub, alice) as a, connect(hub, other_tab_session) as other:
        r = hub.post("/api/auth/logout", headers=alice.headers(csrf=True))
        assert r.status_code == 204
        assert a.receive_json()["code"] == "session_expired"
        with pytest.raises(WebSocketDisconnect) as exc:
            a.receive_json()
        assert exc.value.code == 4401

        # A different session (another device) stays connected.
        other.send_json({"type": "ping"})
        assert other.receive_json() == {"type": "pong"}


def test_connections_are_cleaned_up(hub, alice, bob):
    with connect(hub, alice), connect(hub, bob):
        assert manager.count() == 2
    hub.get("/api/health")  # let the server finish handling the disconnects
    assert manager.count() == 0
