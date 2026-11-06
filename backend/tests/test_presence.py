"""Typing indicator and online / last-seen presence."""

from datetime import datetime

from sqlalchemy import select

from app.models import User
from tests.test_messaging import connect, conversation_id, send, until
from tests.test_messaging import alice, bob, hub  # noqa: F401  (fixtures)


def next_of(ws, *types: str) -> dict:
    """Next event of one of `types` (raw sockets also carry pongs, acks, etc.)."""
    for _ in range(20):
        event = ws.receive_json()
        if event["type"] in types:
            return event
    raise AssertionError(f"no {types} event")


def ping_drain(ws) -> list[dict]:
    """Round-trip a ping and return every event that arrived before the pong."""
    ws.send_json({"type": "ping"})
    seen = []
    while (event := ws.receive_json())["type"] != "pong":
        seen.append(event)
    return seen


# --- presence -----------------------------------------------------------------------


def test_partner_sees_online_then_last_seen(hub, alice, bob, db):
    with connect(hub, bob, raw=True) as b:
        with connect(hub, alice, raw=True):
            online = next_of(b, "presence")
            assert online["userId"] == alice.id and online["online"] is True
        offline = next_of(b, "presence")
        assert offline["online"] is False
        assert datetime.fromisoformat(offline["lastSeenAt"])

    db.expire_all()
    stored = db.scalar(select(User.last_seen_at).where(User.id == alice.user.id))
    assert stored is not None
    assert stored.isoformat() == datetime.fromisoformat(offline["lastSeenAt"]).isoformat()


def test_away_and_back(hub, alice, bob):
    with connect(hub, bob, raw=True) as b, connect(hub, alice, raw=True) as a:
        assert next_of(b, "presence")["online"] is True
        a.send_json({"type": "presence", "state": "away"})  # tab hidden
        assert next_of(b, "presence")["online"] is False
        a.send_json({"type": "presence", "state": "active"})  # tab visible again
        assert next_of(b, "presence")["online"] is True


def test_multiple_tabs_stay_online_until_last_closes(hub, alice, bob):
    with connect(hub, bob, raw=True) as b, connect(hub, alice, raw=True):
        assert next_of(b, "presence")["online"] is True
        with connect(hub, alice, raw=True):
            pass  # second tab opens and closes: still online, no event
        assert [e for e in ping_drain(b) if e["type"] == "presence"] == []
    # (closing the first tab is covered above)


def test_presence_is_not_echoed_to_self(hub, alice):
    with connect(hub, alice, raw=True) as a1, connect(hub, alice, raw=True):
        assert [e for e in ping_drain(a1) if e["type"] == "presence"] == []


def test_conversation_list_reports_presence(hub, alice, bob):
    def partner_of(who, other):
        members = hub.get("/api/conversations", headers=who.headers()).json()["conversations"][0]["members"]
        return next(m for m in members if m["id"] == other.id)

    assert partner_of(bob, alice)["online"] is False
    assert partner_of(bob, alice)["lastSeenAt"] is None
    with connect(hub, alice):
        hub.get("/api/health")
        assert partner_of(bob, alice)["online"] is True
    hub.get("/api/health")
    seen = partner_of(bob, alice)
    assert seen["online"] is False and seen["lastSeenAt"] is not None


# --- typing ---------------------------------------------------------------------------


def test_typing_is_relayed_to_partner_only(hub, alice, bob):
    with connect(hub, bob, raw=True) as b, connect(hub, alice, raw=True) as a1, connect(hub, alice, raw=True) as a2:
        a1.send_json({"type": "typing", "isTyping": True})
        assert next_of(b, "typing") == {"type": "typing", "userId": alice.id, "isTyping": True}
        a1.send_json({"type": "typing", "isTyping": False})
        assert next_of(b, "typing")["isTyping"] is False
        # Alice's other tab never sees her own typing
        assert [e for e in ping_drain(a2) if e["type"] == "typing"] == []


def test_typing_is_throttled(hub, alice, bob):
    with connect(hub, bob, raw=True) as b, connect(hub, alice, raw=True) as a:
        for _ in range(5):
            a.send_json({"type": "typing", "isTyping": True})
        ping_drain(a)  # make sure the server processed them
        typing = [e for e in ping_drain(b) if e["type"] == "typing"]
        assert len(typing) == 1


def test_typing_stops_when_typist_disconnects(hub, alice, bob):
    with connect(hub, bob, raw=True) as b:
        with connect(hub, alice, raw=True) as a:
            a.send_json({"type": "typing", "isTyping": True})
            assert next_of(b, "typing")["isTyping"] is True
        assert next_of(b, "typing")["isTyping"] is False


def test_typing_and_presence_events_are_validated(hub, alice):
    with connect(hub, alice) as a:
        a.send_json({"type": "typing", "isTyping": "yes"})
        assert a.receive_json()["code"] == "invalid_event"
        a.send_json({"type": "presence", "state": "busy"})
        assert a.receive_json()["code"] == "invalid_event"
        a.send_json({"type": "typing", "isTyping": True, "userId": "someone-else"})
        assert a.receive_json()["code"] == "invalid_event"


def test_messaging_still_works_alongside_presence(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        send(a, "hi")
        assert until(a, "message.ack")["message"]["body"] == "hi"
        assert until(b, "message.new")["message"]["body"] == "hi"
    assert conversation_id(hub, alice)
