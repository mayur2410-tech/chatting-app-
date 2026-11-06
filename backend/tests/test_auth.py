from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.service import utcnow
from app.config import get_settings
from app.models import AuthSession
from app.security import hash_token
from app.users import UserProvisioningError, create_user, set_active, set_password
from tests.conftest import FRONTEND_ORIGIN, PASSWORDS, login

COOKIE = "duo_session"


def csrf_headers(response) -> dict[str, str]:
    return {"X-CSRF-Token": response.json()["csrfToken"]}


# --- health -----------------------------------------------------------------


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- login ------------------------------------------------------------------


def test_login_success_sets_hardened_cookie(client, users):
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == {"id": str(users["alex"].id), "username": "alex", "displayName": "Alex"}
    assert len(body["csrfToken"]) == 64
    assert "expiresAt" in body

    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    # Browser-session cookie: gone when the browser closes.
    assert "Max-Age" not in set_cookie
    assert "expires" not in set_cookie.lower()


def test_login_response_never_exposes_password_hash(client, users):
    text = login(client).text.lower()
    assert "password" not in text
    assert "argon2" not in text
    assert users["alex"].password_hash not in login(client).text


def test_username_is_case_insensitive(client, users):
    assert login(client, "  ALEX ", PASSWORDS["alex"]).status_code == 200


def test_wrong_password_and_unknown_user_get_identical_errors(client, users):
    wrong = login(client, "alex", "not the password")
    unknown = login(client, "nobody", "whatever password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid username or password"}
    assert "set-cookie" not in wrong.headers


def test_only_provisioned_users_can_authenticate(client, users, db):
    assert login(client, "alex").status_code == 200
    assert login(client, "sam").status_code == 200
    assert login(client, "mallory", "some password!!").status_code == 401

    with pytest.raises(UserProvisioningError):
        create_user(db, get_settings(), "mallory", "Mallory", "a third long password")


def test_deactivated_user_cannot_log_in_and_loses_sessions(client, users, db):
    r = login(client)
    set_active(db, get_settings(), "alex", False)
    assert client.get("/api/auth/me").status_code == 401
    assert login(client).status_code == 401
    assert r.status_code == 200


def test_validation_errors_do_not_echo_input(client, users):
    secret = "S" * 300
    r = client.post("/api/auth/login", json={"username": "alex", "password": secret})
    assert r.status_code == 422
    assert secret not in r.text
    assert r.json()["fields"] == ["password"]

    assert client.post("/api/auth/login", json={"username": "alex"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "alex", "password": "x", "admin": True}).status_code == 422


# --- sessions ---------------------------------------------------------------


def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE, "forged-token")
    assert client.get("/api/auth/me").status_code == 401


def test_session_persists_across_page_reloads(app, client, users):
    r = login(client)
    token = client.cookies.get(COOKIE)

    # A brand-new client carrying only the cookie, as after a browser refresh.
    reloaded = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    reloaded.cookies.set(COOKIE, token)
    me = reloaded.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alex"
    assert me.json()["csrfToken"] == r.json()["csrfToken"]


def test_session_token_is_stored_only_as_hash(client, users, db):
    login(client)
    token = client.cookies.get(COOKIE)
    stored = db.scalars(select(AuthSession.token_hash)).all()
    assert stored == [hash_token(token)]
    assert token not in stored


def test_absolute_expiry(client, users, db):
    login(client)
    session = db.scalars(select(AuthSession)).one()
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_idle_expiry(client, users, db):
    login(client)
    session = db.scalars(select(AuthSession)).one()
    session.last_seen_at = utcnow() - timedelta(minutes=get_settings().session_idle_minutes + 1)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_login_rotates_existing_session(client, users, db):
    login(client)
    first = client.cookies.get(COOKIE)
    login(client)
    second = client.cookies.get(COOKIE)
    assert first != second
    old = db.scalars(select(AuthSession).where(AuthSession.token_hash == hash_token(first))).one()
    assert old.revoked_at is not None


# --- logout & revocation ----------------------------------------------------


def test_logout_revokes_session(client, users, db):
    r = login(client)
    token = client.cookies.get(COOKIE)

    out = client.post("/api/auth/logout", headers=csrf_headers(r))
    assert out.status_code == 204
    assert f'{COOKIE}=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]

    # Even replaying the old cookie must fail.
    client.cookies.set(COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401
    row = db.scalars(select(AuthSession)).one()
    assert row.revoked_at is not None


def test_logout_without_session_is_idempotent(client):
    assert client.post("/api/auth/logout").status_code == 204


def test_password_change_revokes_all_sessions(client, users, db):
    login(client)
    set_password(db, "alex", "a brand new long password")
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, "alex", "a brand new long password").status_code == 200


def test_sessions_are_per_user(app, users):
    a = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    b = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    login(a, "alex")
    login(b, "sam")
    assert a.get("/api/auth/me").json()["user"]["username"] == "alex"
    assert b.get("/api/auth/me").json()["user"]["username"] == "sam"


# --- CSRF & origin ----------------------------------------------------------


def test_logout_requires_csrf_token(client, users):
    login(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "0" * 64}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200  # still signed in


def test_csrf_token_from_other_session_is_rejected(app, users):
    a = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    b = TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})
    login(a, "alex")
    other = login(b, "sam")
    assert a.post("/api/auth/logout", headers=csrf_headers(other)).status_code == 403


def test_untrusted_origin_is_rejected(client, users):
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}):
        r = client.post(
            "/api/auth/login", json={"username": "alex", "password": PASSWORDS["alex"]}, headers=headers
        )
        assert r.status_code == 403


def test_missing_origin_is_rejected(app, users):
    bare = TestClient(app, base_url="http://localhost")
    r = bare.post("/api/auth/login", json={"username": "alex", "password": PASSWORDS["alex"]})
    assert r.status_code == 403


def test_referer_is_accepted_when_origin_missing(app, users):
    bare = TestClient(app, base_url="http://localhost", headers={"Referer": f"{FRONTEND_ORIGIN}/"})
    assert login(bare).status_code == 200


def test_untrusted_host_is_rejected(app):
    evil = TestClient(app, base_url="http://evil.example")
    assert evil.get("/api/health").status_code == 400


def test_cors_allows_only_configured_origin(client):
    ok = client.options(
        "/api/auth/login",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN
    assert ok.headers.get("access-control-allow-credentials") == "true"

    bad = client.options(
        "/api/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


# --- rate limiting ----------------------------------------------------------


def test_per_user_rate_limit(client, users):
    limit = get_settings().login_max_failures_per_user
    for _ in range(limit):
        assert login(client, "alex", "wrong password").status_code == 401

    blocked = login(client, "alex")  # even the correct password is refused while blocked
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json() == {"detail": "Too many attempts. Try again later."}

    assert login(client, "sam").status_code == 200  # other account unaffected


def test_per_ip_rate_limit(client, users):
    limit = get_settings().login_max_failures_per_ip
    for i in range(limit):
        assert login(client, f"ghost{i}", "wrong password").status_code == 401
    assert login(client, "sam").status_code == 429


def test_successful_login_resets_user_counter(client, users):
    limit = get_settings().login_max_failures_per_user
    for _ in range(limit - 1):
        login(client, "alex", "wrong password")
    assert login(client).status_code == 200
    for _ in range(limit - 1):
        assert login(client, "alex", "wrong password").status_code == 401


# --- headers ----------------------------------------------------------------


def test_security_headers(client, users):
    r = login(client)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in r.headers["x-robots-tag"]


def test_docs_disabled_outside_development(client):
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_login_rate_limit_can_be_switched_off(client, users, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit_enabled", False)
    for _ in range(get_settings().login_max_failures_per_user + 3):
        assert login(client, "alex", "wrong password").status_code == 401
    assert login(client).status_code == 200  # never locked out
