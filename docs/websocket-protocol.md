# Duo messaging protocol

Messages are plain text protected by login, membership checks and (in deployment) HTTPS. They are
not end-to-end encrypted; see the README "Privacy model".

## Model

- Exactly one conversation, shared by the two accounts. It is created automatically the first time
  either user asks for it once both accounts exist.
- The server assigns `id` (UUID), `seq` (strictly increasing; ordering + pagination cursor),
  `senderId` (from the session, never from the client) and `createdAt`.
- `replyToId` (optional) points at a live message in the same conversation.
- Idempotency: `(senderId, clientMessageId)` is unique. Re-sending the same `clientMessageId`
  returns the original message instead of creating another.
- **Clear chat** is per member: the server remembers `cleared_through_seq` for each member and hides
  messages at or before it from that member only. Nothing is deleted.

### Delivery states (client)

| State | Meaning | Trigger |
| --- | --- | --- |
| `sending` | accepted locally, queued/retrying | user pressed send |
| `sent` | **stored** by the server | `message.ack` |
| `delivered` | **received** by the other person's device | `message.delivered` |
| `failed` | rejected; not retried | `error` with `clientMessageId` |

## HTTP endpoints

All require the session cookie; non-members get `404`. State-changing requests also need the
`X-CSRF-Token` header and an allowed `Origin`.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/conversations` | `{conversations: [{id, members: [{id, displayName, online, lastSeenAt}], createdAt}], maxBodyChars}` |
| GET | `/api/conversations/{id}/messages?limit=50` | latest page; `before=<seq>` older page; `after=<seq>` catch-up (not both → 400). `{messages (ascending), hasMore, syncedAt}`. Excludes deleted messages and anything the caller cleared. |
| GET | `/api/conversations/{id}/deletions?since=<syncedAt>` | `{deleted: [{id, senderId, clientMessageId}], syncedAt}`, deletions missed while offline. |
| POST | `/api/conversations/{id}/clear` | clear for the caller only → `{clearedThroughSeq}`; sends `conversation.cleared` to the caller's other open tabs. |
| DELETE | `/api/messages/{id}` | deletes **for both users**; only the **sender** may delete (others 403). 204, idempotent. Broadcasts `message.deleted`. The text is wiped; a tombstone remains for syncing. |

## WebSocket `WS /api/ws/chat`

**Handshake:** same-origin; the browser sends the `HttpOnly` session cookie. `Origin` must be in
`ALLOWED_ORIGINS`, the session valid, and the user a member. Otherwise the handshake is refused (403).

**Frames:** text frames with one JSON object, ≤ 64 KiB. Binary frames close the socket with `1003`.
Field names are camelCase; unknown fields are rejected (so a client cannot supply `senderId`).

### Client → server

```jsonc
// body: 1..4000 characters, not blank. replyToId optional.
{"type": "message.send", "clientMessageId": "<uuid v4>", "body": "Hi ✈️", "replyToId": "<message id> | null"}

// This device has received these messages (1..100 ids). Ignored for the sender's own messages.
{"type": "message.delivered", "messageIds": ["<message id>"]}

// Typing indicator: send true while typing (at most every ~2.5 s), false when done.
{"type": "typing", "isTyping": true}

// Presence: "active" while this tab shows the chat, "away" when it is hidden.
{"type": "presence", "state": "active"}

{"type": "ping"}
```

### Server → client

```jsonc
{"type": "message.ack", "clientMessageId": "<uuid>", "message": Message}      // to the sending socket
{"type": "message.new", "message": Message}                                   // to every other socket
{"type": "message.delivered", "messageId": "<id>", "deliveredAt": "<iso>"}    // to every socket
{"type": "message.deleted", "messageId": "<id>", "senderId": "<id>", "clientMessageId": "<uuid>"}
{"type": "conversation.cleared", "clearedThroughSeq": 51}                     // only to the clearing user
{"type": "typing", "userId": "<id>", "isTyping": true}                        // to the partner only (never stored)
{"type": "presence", "userId": "<id>", "online": false, "lastSeenAt": "<iso>"} // to the partner, when online flips
{"type": "error", "code": "<code>", "message": "<text>", "clientMessageId"?: "<uuid>", "retryAfter"?: 5}
{"type": "pong"}
```

`Message` = `{id, seq, conversationId, senderId, clientMessageId, body, replyToId, createdAt, deliveredAt}`.

**Presence rules.** A user is *online* while at least one of their open tabs reports `active`
(connected and visible). When that flips, the server records `users.last_seen_at` and sends a
`presence` event to the partner. `GET /api/conversations` also returns each member's `online` and
`lastSeenAt`, and clients re-fetch it after reconnecting. Typing events are relayed live and never
stored; the server forwards a repeated `true` at most every 2 s, sends `false` if the typist
disconnects, and clients hide a stale indicator after 6 s. Times are shown in IST, 12-hour.

### Error codes

| Code | Meaning | Socket |
| --- | --- | --- |
| `invalid_json` | frame is not JSON | stays open |
| `invalid_event` | schema/size validation failed (incl. blank or > 4000-char body) | stays open |
| `invalid_reply` | `replyToId` is not a live message in this conversation | stays open |
| `payload_too_large` | frame > 64 KiB | stays open |
| `rate_limited` | over `MESSAGE_RATE_LIMIT` per `MESSAGE_RATE_WINDOW_SECONDS`; retry after `retryAfter` | stays open |
| `unsupported_data` | binary frame | closed `1003` |
| `session_expired` | session expired, revoked or logged out | closed `4401` |
| `internal_error` | unexpected server error | stays open |

Close codes: `4401` session ended (stop, sign in again); `4403` not allowed (stop); anything else →
reconnect with backoff.

### Client behaviour (reference: `frontend/src/messaging/`)

1. Load `/api/conversations`, then the latest page of history; remember `syncedAt`.
2. Open the socket. On every open (first connect and each reconnect): fetch `messages?after=<highest
   seq>` until `hasMore` is false; fetch `deletions?since=<syncedAt>` and remove those; re-send every
   message still `sending` (same `clientMessageId`, so no duplicates); send `message.delivered` for
   received messages.
3. Re-transmit if no ack within 10 s, after `retryAfter` on `rate_limited`, and on reconnect.
4. Reconnect with exponential backoff (1 s → 30 s, jittered), and immediately when the browser comes
   back online or the tab becomes visible. Ping every 25 s; no pong within 10 s → reconnect.

Each open socket re-validates its session every `WS_AUTH_RECHECK_SECONDS` (default 30 s) and is closed
with `4401` once it is no longer valid; logout closes that session's sockets immediately.

## Deployment note: single process

Live connections and rate limiters are kept in memory. That is correct for the single-process
deployment this project uses; multiple workers would need a shared event bus (Redis Pub/Sub or
Postgres `LISTEN/NOTIFY`) and a shared rate-limit store.

## What the server stores

Usernames, display names and password hashes; session timestamps; each user's last-seen time; and for each message the sender,
text, reply link, and created/delivered/deleted times. No IP addresses or browser details.
