# Duo ✈️

A simple, private, real-time chat for exactly two people, with an aviation theme.

- **Two accounts only.** Each person has their own username and password, created by the admin from
  the command line. There is no sign-up, so nobody else can join.
- **Real-time.** Messages arrive instantly over a WebSocket and are saved in PostgreSQL, so the chat
  is still there after a refresh, on another device, or after reconnecting.
- **Hidden until Reveal.** Bubbles show dots until you tap Reveal (or Reveal all). They hide again
  after 20 seconds, on Hide all, or when you switch away from the app.
- **Reply.** Swipe a message to the right (finger on phones, mouse drag on computers) or tap the ↩ button. The reply quotes the
  original; tap the quote to jump to it.
- **Clear chat (just for you).** Menu ⋮ → Clear chat removes the history from *your* view only. Your
  partner still sees the whole conversation, and new messages keep arriving for both of you.
- **Typing, online and last seen.** Under the other person's name: *typing…* while they type, *online*
  while they have the chat open, otherwise *last seen today at 3:45 PM* (WhatsApp-style).
- **India time.** All times (messages, dates, last seen) are shown in IST with a 12-hour clock.
- **Delete a message** you sent removes it for both of you.
- **Closing the tab or browser signs you out.** Reopening the app shows the sign-in screen; a normal
  refresh keeps you signed in. (The login cookie lasts only for the browser session, and a per-tab
  marker in `sessionStorage` makes a new tab sign out any leftover session. Browsers set to "continue
  where you left off" may restore tabs and stay signed in; that's a browser feature.)
- **Delivery ticks:** ⏱ sending → ✈ sent (saved on the server) → 🛬 delivered (reached the other person's device).
- Emoji picker, light/dark mode, mobile-first layout.

## Privacy model

Messages are protected by your login, by server-side access checks (only the two members can read the
conversation), and by HTTPS once deployed. They are **not end-to-end encrypted**: whoever runs the
server or has the database can read them. (An end-to-end encrypted version was built in Phase 4 and
removed at the owners' request to keep the app simple; its code is kept in `archive/phase4-e2ee.zip`.)

## Layout

```
.
├── docker-compose.yml          # local PostgreSQL 16 (loopback only) + duo_test database
├── .env.example                # POSTGRES_* for docker compose
├── archive/phase4-e2ee.zip     # removed end-to-end encryption code (for reference)
├── docs/websocket-protocol.md  # messaging HTTP + WebSocket protocol
├── backend/
│   ├── .venv/                  # Python 3.12 virtual environment (not committed)
│   ├── .env.example
│   ├── requirements.txt / requirements-dev.txt
│   ├── alembic.ini, alembic/versions/
│   ├── app/
│   │   ├── main.py             # app factory, middleware (hosts, CORS, origin check, security headers)
│   │   ├── config.py           # env-based settings
│   │   ├── db.py, models.py    # users, sessions, conversations, members, messages
│   │   ├── security.py         # Argon2id, session tokens, CSRF HMAC
│   │   ├── rate_limit.py       # sliding-window limiters (login failures, message sends)
│   │   ├── users.py, cli.py    # account provisioning (CLI only, max 2 users)
│   │   ├── auth/               # login, logout, session checks
│   │   └── messaging/          # HTTP routes, WebSocket endpoint, service, connection manager
│   └── tests/                  # pytest, runs against duo_test
└── frontend/                   # React + Vite + TypeScript + Tailwind
    └── src/
        ├── api/                # fetch client, auth + messaging calls
        ├── messaging/          # protocol types, ChatSocket, useConversation
        ├── components/chat/    # header, message list, bubble (swipe-to-reply), composer, emoji picker
        └── screens/            # LoginScreen, ChatScreen
```

## First-time setup

Requires Docker Desktop, Python 3.12 and Node 20+.

```bash
# 1. Secrets (use long random values; keep the two files' DB passwords in sync)
cp .env.example .env
cp backend/.env.example backend/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # → SECRET_KEY in backend/.env

# 2. Database
docker compose up -d --wait

# 3. Backend virtual environment (always use backend/.venv)
cd backend
py -3.12 -m venv .venv                     # macOS/Linux: python3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m alembic upgrade head

# 4. Create the two accounts (password prompt is hidden; minimum length = MIN_PASSWORD_LENGTH, default 12)
.venv/Scripts/python -m app.cli create-user --username mayur --display-name Mayur
.venv/Scripts/python -m app.cli create-user --username friend --display-name Friend

# 5. Frontend
cd ../frontend && npm install
```

## Run

```bash
# terminal 1: API on 127.0.0.1:8000
cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-max-size 65536 --reload

# terminal 2: UI on http://localhost:5173 (proxies /api to the backend)
cd frontend && npm run dev
```

## Trying it with two people on one computer

Cookies are per host, so `localhost` and `127.0.0.1` behave like two separate browsers:

1. In `backend/.env` set `ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` and restart the API.
2. Window A: http://localhost:5173 → sign in as the first account.
3. Window B: http://127.0.0.1:5173 (or a private window / another browser) → sign in as the second account.
4. Chat: messages appear instantly on the other side. Reply, delete, and Clear chat as described above.

On phones on the same Wi-Fi, also add `http://<PC-IP>:5173` to `ALLOWED_ORIGINS` and the IP to
`ALLOWED_HOSTS`. (Safari on iPhone needs HTTPS for the login cookie; that comes with deployment in Phase 6.)

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest      # uses TEST_DATABASE_URL (duo_test), wiped per test
cd frontend && npm run build                      # type-check + production build
```

## Migrations

```bash
cd backend
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic revision --autogenerate -m "describe change"
.venv/Scripts/python -m alembic check             # fails if models and migrations disagree
```

## Account administration

```bash
python -m app.cli list-users
python -m app.cli set-password    --username mayur   # also signs mayur out everywhere
python -m app.cli revoke-sessions --username mayur
python -m app.cli deactivate-user --username mayur
python -m app.cli activate-user   --username mayur
python -m app.cli purge-sessions                     # delete expired/revoked session rows
```

## API

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/health` | – | `{"status":"ok"}` or 503 |
| POST | `/api/auth/login` | – | `{username, password}` → session cookie + `{user, csrfToken, expiresAt}`; generic 401; 429 when rate-limited |
| GET | `/api/auth/me` | cookie | current user, or 401 |
| POST | `/api/auth/logout` | cookie + CSRF | ends the session and its live connections |
| GET | `/api/conversations` | cookie | the single shared conversation |
| GET | `/api/conversations/{id}/messages` | cookie | history (`before` / `after` cursors, `limit` ≤ 100), minus anything you cleared |
| GET | `/api/conversations/{id}/deletions?since=` | cookie | deletions missed while offline |
| POST | `/api/conversations/{id}/clear` | cookie + CSRF | clear chat for you only |
| DELETE | `/api/messages/{id}` | cookie + CSRF | delete your own message for both of you |
| WS | `/api/ws/chat` | cookie + allowed `Origin` | live messages, replies, delivery receipts, deletions |

Full protocol: [`docs/websocket-protocol.md`](docs/websocket-protocol.md).

## Security notes

- **Passwords:** Argon2id; unknown usernames take the same time as wrong passwords; generic errors.
- **Sessions:** random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` + `__Host-`
  in production); only its hash is stored; 12 h lifetime, 60 min idle timeout; logout and password
  changes end sessions immediately.
- **CSRF and origins:** CSRF token on every state-changing request; requests and WebSockets must come
  from an allowed origin; trusted hosts only.
- **Rate limits:** login failures per username/IP and messages per user. These are in memory, so the API
  runs as a single process (more workers would need e.g. Redis).
- **Messages:** sender always taken from the session; replies must point to a live message in the same
  conversation; 4000-character limit; deleting wipes the text; message text is never logged.
- **Headers:** `no-store` caching, `nosniff`, no framing, `no-referrer`, `noindex`.

## Status

| Phase | Scope | Status |
| --- | --- | --- |
| 1–3 | UI, accounts and sessions, real-time messaging | ✅ |
| 4 | End-to-end encryption | Built, then removed by request (archived) |
| Simplification | Login straight to chat, reply, clear chat, aviation theme | ✅ |
| 5 | Auto-hide/sign-out on inactivity, retention policy | Planned |
| 6 | Security testing, Docker Compose + Caddy HTTPS deployment | Planned |
