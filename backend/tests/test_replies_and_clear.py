"""Swipe-to-reply and per-user "Clear chat"."""

import uuid

from fastapi.testclient import TestClient

from tests.test_messaging import Identity, connect, conversation_id, history, send, until
from tests.test_messaging import alice, bob, hub  # noqa: F401  (fixtures)


def send_and_ack(ws, text: str, **extra) -> dict:
    send(ws, text, **extra)
    return until(ws, "message.ack")["message"]


# --- replies -------------------------------------------------------------------


def test_reply_is_stored_and_delivered(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        original = send_and_ack(a, "Dinner at 8?")
        until(b, "message.new")
        reply = send_and_ack(b, "Yes! ✈️", replyToId=original["id"])
        assert reply["replyToId"] == original["id"]
        assert until(a, "message.new")["message"]["replyToId"] == original["id"]

    page = history(hub, alice)
    assert [(m["body"], m["replyToId"]) for m in page["messages"]] == [
        ("Dinner at 8?", None),
        ("Yes! ✈️", original["id"]),
    ]


def test_reply_to_unknown_or_deleted_message_is_rejected(hub, alice, bob):
    with connect(hub, alice) as a:
        cid = send(a, "reply to nothing", replyToId=str(uuid.uuid4()))
        err = until(a, "error")
        assert (err["code"], err["clientMessageId"]) == ("invalid_reply", cid)

        gone = send_and_ack(a, "soon deleted")
        assert hub.delete(f"/api/messages/{gone['id']}", headers=alice.headers(csrf=True)).status_code == 204
        until(a, "message.deleted")
        send(a, "reply to deleted", replyToId=gone["id"])
        assert until(a, "error")["code"] == "invalid_reply"


def test_reply_shows_original_even_after_clearing_chat(hub, alice, bob):
    """Alice clears her chat; Bob then replies to an old message. Alice still sees what it quotes."""
    with connect(hub, alice) as a, connect(hub, bob) as b:
        original = send_and_ack(a, "Old plan: dinner at 8")
        until(b, "message.new")
        hub.post(f"/api/conversations/{conversation_id(hub, alice)}/clear", headers=alice.headers(csrf=True))
        until(a, "conversation.cleared")

        send_and_ack(b, "Still on?", replyToId=original["id"])
        live = until(a, "message.new")["message"]
        assert live["replyTo"] == {
            "id": original["id"],
            "senderId": alice.id,
            "body": "Old plan: dinner at 8",
            "deleted": False,
        }

    page = history(hub, alice)["messages"]
    assert [m["body"] for m in page] == ["Still on?"]  # the original stays cleared for Alice
    assert page[0]["replyTo"]["body"] == "Old plan: dinner at 8"


def test_reply_survives_deletion_of_the_original(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        original = send_and_ack(a, "original")
        until(b, "message.new")
        send_and_ack(b, "the reply", replyToId=original["id"])
    hub.delete(f"/api/messages/{original['id']}", headers=alice.headers(csrf=True))
    page = history(hub, bob)
    # The reply stays; its quote says the original was deleted, without its text.
    assert [(m["body"], m["replyToId"]) for m in page["messages"]] == [("the reply", original["id"])]
    assert page["messages"][0]["replyTo"] == {"id": original["id"], "senderId": alice.id, "body": "", "deleted": True}


# --- clear chat -----------------------------------------------------------------


def test_clear_chat_only_affects_the_user_who_cleared(hub, alice, bob):
    with connect(hub, alice) as a, connect(hub, bob) as b:
        for text in ("one", "two", "three"):
            send_and_ack(a, text)
            until(b, "message.new")

        cid = conversation_id(hub, alice)
        r = hub.post(f"/api/conversations/{cid}/clear", headers=alice.headers(csrf=True))
        assert r.status_code == 200
        through = r.json()["clearedThroughSeq"]
        assert until(a, "conversation.cleared") == {"type": "conversation.cleared", "clearedThroughSeq": through}

        # Alice sees nothing; Bob still sees everything.
        assert history(hub, alice)["messages"] == []
        assert [m["body"] for m in history(hub, bob)["messages"]] == ["one", "two", "three"]

        # New messages appear for both as usual.
        send_and_ack(b, "four")
        assert until(a, "message.new")["message"]["body"] == "four"
    assert [m["body"] for m in history(hub, alice)["messages"]] == ["four"]
    assert [m["body"] for m in history(hub, bob)["messages"]] == ["one", "two", "three", "four"]


def test_clear_event_goes_only_to_the_clearing_user(hub, alice, bob):
    with connect(hub, alice) as a1, connect(hub, alice) as a2, connect(hub, bob) as b:
        send_and_ack(a1, "hello")
        until(a2, "message.new")
        until(b, "message.new")
        hub.post(f"/api/conversations/{conversation_id(hub, alice)}/clear", headers=alice.headers(csrf=True))
        until(a1, "conversation.cleared")
        until(a2, "conversation.cleared")  # Alice's other tab
        b.send_json({"type": "ping"})
        assert b.receive_json() == {"type": "pong"}  # Bob got no clear event


def test_cleared_messages_stay_hidden_for_catch_up_and_paging(hub, alice):
    with connect(hub, alice) as a:
        first = send_and_ack(a, "before clear")
        hub.post(f"/api/conversations/{conversation_id(hub, alice)}/clear", headers=alice.headers(csrf=True))
        send_and_ack(a, "after clear")
    assert [m["body"] for m in history(hub, alice, after=0)["messages"]] == ["after clear"]
    assert history(hub, alice, before=first["seq"] + 1)["messages"] == []


def test_clearing_twice_and_empty_chats_are_fine(hub, alice):
    cid = conversation_id(hub, alice)
    r1 = hub.post(f"/api/conversations/{cid}/clear", headers=alice.headers(csrf=True))
    r2 = hub.post(f"/api/conversations/{cid}/clear", headers=alice.headers(csrf=True))
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["clearedThroughSeq"] == r2.json()["clearedThroughSeq"] == 0


def test_clear_requires_auth_csrf_and_membership(hub, alice: Identity, bob: Identity):
    cid = conversation_id(hub, alice)
    assert hub.post(f"/api/conversations/{cid}/clear").status_code == 401
    assert hub.post(f"/api/conversations/{cid}/clear", headers=alice.headers()).status_code == 403  # no CSRF
    assert (
        hub.post(f"/api/conversations/{uuid.uuid4()}/clear", headers=alice.headers(csrf=True)).status_code == 404
    )
    evil = TestClient(hub.app, base_url="http://localhost", headers={"Origin": "https://evil.example"})
    assert evil.post(f"/api/conversations/{cid}/clear", headers=alice.headers(csrf=True)).status_code == 403
