"""
HTTP response models and the WebSocket event protocol. See docs/websocket-protocol.md.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator
from pydantic.alias_generators import to_camel

from app.auth.schemas import ApiModel
from app.models import Message

MAX_BODY_CHARS = 4_000
MAX_FRAME_CHARS = 65_536
MAX_DELIVERED_BATCH = 100


# --- HTTP -------------------------------------------------------------------


REPLY_PREVIEW_CHARS = 300


class ReplyPreviewOut(ApiModel):
    """What a reply quotes. `body` is empty when the original was deleted for everyone."""

    id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    deleted: bool


class MessageOut(ApiModel):
    id: uuid.UUID
    seq: int
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    client_message_id: uuid.UUID
    body: str
    reply_to_id: uuid.UUID | None
    reply_to: ReplyPreviewOut | None
    created_at: datetime
    delivered_at: datetime | None

    @classmethod
    def of(cls, m: Message) -> "MessageOut":
        return cls(
            id=m.id,
            seq=m.seq,
            conversation_id=m.conversation_id,
            sender_id=m.sender_id,
            client_message_id=m.client_message_id,
            body=m.body,
            reply_to_id=m.reply_to_id,
            reply_to=(
                ReplyPreviewOut(
                    id=m.reply_to.id,
                    sender_id=m.reply_to.sender_id,
                    body=m.reply_to.body[:REPLY_PREVIEW_CHARS],
                    deleted=m.reply_to.deleted_at is not None,
                )
                if m.reply_to is not None
                else None
            ),
            created_at=m.created_at,
            delivered_at=m.delivered_at,
        )

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class MemberOut(ApiModel):
    id: uuid.UUID
    display_name: str
    # Presence: online = has the chat open and visible right now.
    online: bool = False
    last_seen_at: datetime | None = None


class ConversationOut(ApiModel):
    id: uuid.UUID
    members: list[MemberOut]
    created_at: datetime


class ConversationListOut(ApiModel):
    conversations: list[ConversationOut]
    max_body_chars: int


class MessagePageOut(ApiModel):
    messages: list[MessageOut]
    has_more: bool
    # Pass to /deletions?since= on reconnect to learn about deletions missed while offline.
    synced_at: datetime


class DeletedRef(ApiModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    client_message_id: uuid.UUID


class DeletionsOut(ApiModel):
    deleted: list[DeletedRef]
    synced_at: datetime


class ClearedOut(ApiModel):
    """Messages with seq <= cleared_through_seq are hidden from this user only."""

    cleared_through_seq: int


# --- WebSocket: client → server --------------------------------------------


class _ClientEvent(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True)


class SendEvent(_ClientEvent):
    type: Literal["message.send"]
    client_message_id: uuid.UUID
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    reply_to_id: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty message")
        return value


class DeliveredEvent(_ClientEvent):
    type: Literal["message.delivered"]
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_DELIVERED_BATCH)


class PingEvent(_ClientEvent):
    type: Literal["ping"]


class TypingEvent(_ClientEvent):
    """Relayed live to the partner; never stored."""

    type: Literal["typing"]
    is_typing: StrictBool  # true/false only; no coercion from strings like "yes"


class PresenceEvent(_ClientEvent):
    """'active' while the chat is open and visible on this tab, 'away' when hidden."""

    type: Literal["presence"]
    state: Literal["active", "away"]


ClientEvent = Annotated[
    SendEvent | DeliveredEvent | PingEvent | TypingEvent | PresenceEvent, Field(discriminator="type")
]
client_event_adapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


# --- WebSocket: server → client --------------------------------------------


def ev_new(message: MessageOut) -> dict[str, Any]:
    return {"type": "message.new", "message": message.wire()}


def ev_ack(client_message_id: uuid.UUID, message: MessageOut) -> dict[str, Any]:
    return {"type": "message.ack", "clientMessageId": str(client_message_id), "message": message.wire()}


def ev_delivered(message_id: uuid.UUID, delivered_at: datetime) -> dict[str, Any]:
    return {"type": "message.delivered", "messageId": str(message_id), "deliveredAt": delivered_at.isoformat()}


def ev_deleted(message_id: uuid.UUID, sender_id: uuid.UUID, client_message_id: uuid.UUID) -> dict[str, Any]:
    return {
        "type": "message.deleted",
        "messageId": str(message_id),
        "senderId": str(sender_id),
        "clientMessageId": str(client_message_id),
    }


def ev_cleared(cleared_through_seq: int) -> dict[str, Any]:
    """Sent only to the user who cleared the chat (their other tabs/devices)."""
    return {"type": "conversation.cleared", "clearedThroughSeq": cleared_through_seq}


def ev_error(
    code: str, message: str, *, client_message_id: uuid.UUID | None = None, retry_after: int | None = None
) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "error", "code": code, "message": message}
    if client_message_id is not None:
        event["clientMessageId"] = str(client_message_id)
    if retry_after is not None:
        event["retryAfter"] = retry_after
    return event


def ev_typing(user_id: uuid.UUID, is_typing: bool) -> dict[str, Any]:
    return {"type": "typing", "userId": str(user_id), "isTyping": is_typing}


def ev_presence(user_id: uuid.UUID, online: bool, last_seen_at: datetime | None) -> dict[str, Any]:
    return {
        "type": "presence",
        "userId": str(user_id),
        "online": online,
        "lastSeenAt": last_seen_at.isoformat() if last_seen_at else None,
    }


EV_PONG: dict[str, Any] = {"type": "pong"}
