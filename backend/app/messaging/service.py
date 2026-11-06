"""
Conversation and message persistence. Synchronous (SQLAlchemy sessions); async callers wrap
these in run_in_threadpool.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.auth.service import utcnow
from app.models import Conversation, ConversationMember, Message, User

# Arbitrary constant key for the advisory lock that serialises conversation creation.
_CONVERSATION_LOCK_KEY = 0x0D_0C_0A_01
# Reported sync timestamps are pulled back slightly so a deletion committing concurrently with a
# read is never skipped. Replaying a deletion is harmless.
_SYNC_SAFETY_MARGIN = timedelta(seconds=5)


def sync_timestamp() -> datetime:
    return utcnow() - _SYNC_SAFETY_MARGIN


# --- conversations ----------------------------------------------------------


def get_user_conversation(db: Session, user_id: uuid.UUID) -> Conversation | None:
    """The conversation this user belongs to, creating the shared one on first use."""
    conversation = _conversation_for(db, user_id)
    if conversation is None:
        _ensure_conversation(db)
        conversation = _conversation_for(db, user_id)
    return conversation


def _conversation_for(db: Session, user_id: uuid.UUID) -> Conversation | None:
    return db.scalar(
        select(Conversation)
        .join(ConversationMember)
        .where(ConversationMember.user_id == user_id)
        .options(selectinload(Conversation.members).selectinload(ConversationMember.user))
    )


def _ensure_conversation(db: Session) -> None:
    """Create the single conversation once exactly two active accounts exist."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CONVERSATION_LOCK_KEY})
    if db.scalar(select(exists().select_from(Conversation))):
        db.commit()
        return
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.created_at)).all()
    if len(users) != 2:
        db.commit()
        return
    conversation = Conversation(members=[ConversationMember(user_id=u.id) for u in users])
    db.add(conversation)
    db.commit()


def is_member(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id
                )
            )
        )
    )


# --- messages ---------------------------------------------------------------


@dataclass(frozen=True)
class NewMessage:
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    client_message_id: uuid.UUID
    body: str
    reply_to_id: uuid.UUID | None = None


def store_message(db: Session, new: NewMessage) -> tuple[Message, bool]:
    """
    Insert idempotently on (sender_id, client_message_id).
    Returns (message, created). A retry returns the original row with created=False.
    """
    inserted_id = db.scalar(
        insert(Message)
        .values(
            id=uuid.uuid4(),
            conversation_id=new.conversation_id,
            sender_id=new.sender_id,
            client_message_id=new.client_message_id,
            body=new.body,
            reply_to_id=new.reply_to_id,
        )
        .on_conflict_do_nothing(index_elements=["sender_id", "client_message_id"])
        .returning(Message.id)
    )
    if inserted_id is not None:
        db.execute(update(Conversation).where(Conversation.id == new.conversation_id).values(updated_at=utcnow()))
    db.commit()
    message = db.scalar(
        select(Message).where(Message.sender_id == new.sender_id, Message.client_message_id == new.client_message_id)
    )
    assert message is not None
    return message, inserted_id is not None


def find_by_client_id(db: Session, sender_id: uuid.UUID, client_message_id: uuid.UUID) -> Message | None:
    return db.scalar(
        select(Message).where(Message.sender_id == sender_id, Message.client_message_id == client_message_id)
    )


def is_valid_reply_target(db: Session, conversation_id: uuid.UUID, message_id: uuid.UUID) -> bool:
    """A reply must point at a live message in the same conversation."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    Message.id == message_id,
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None),
                )
            )
        )
    )


def list_messages(
    db: Session,
    conversation_id: uuid.UUID,
    *,
    before: int | None,
    after: int | None,
    limit: int,
    cleared_through: int = 0,
) -> tuple[list[Message], bool]:
    """
    Live (non-deleted) messages in ascending order, plus whether more exist in that direction.
    Messages at or before `cleared_through` (this user's "Clear chat" point) are excluded.
    """
    query = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.deleted_at.is_(None),
        Message.seq > cleared_through,
    )
    if after is not None:
        rows = list(db.scalars(query.where(Message.seq > after).order_by(Message.seq.asc()).limit(limit + 1)))
        return rows[:limit], len(rows) > limit
    if before is not None:
        query = query.where(Message.seq < before)
    rows = list(db.scalars(query.order_by(Message.seq.desc()).limit(limit + 1)))
    return list(reversed(rows[:limit])), len(rows) > limit


def list_deletions(db: Session, conversation_id: uuid.UUID, since: datetime) -> list[Message]:
    return list(
        db.scalars(
            select(Message).where(Message.conversation_id == conversation_id, Message.deleted_at > since)
        )
    )


class DeleteResult(enum.Enum):
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    DELETED = "deleted"
    ALREADY_DELETED = "already_deleted"


def delete_message(db: Session, message_id: uuid.UUID, user_id: uuid.UUID) -> tuple[DeleteResult, Message | None]:
    """
    Delete for everyone. Only the sender may delete. The text is wiped immediately; a
    tombstone (ids + deleted_at) remains so the other user's devices can sync the removal.
    """
    message = db.get(Message, message_id)
    if message is None or not is_member(db, message.conversation_id, user_id):
        return DeleteResult.NOT_FOUND, None
    if message.sender_id != user_id:
        return DeleteResult.FORBIDDEN, None
    if message.deleted_at is not None:
        return DeleteResult.ALREADY_DELETED, message
    message.deleted_at = utcnow()
    message.body = ""
    db.commit()
    return DeleteResult.DELETED, message


def mark_delivered(
    db: Session, conversation_id: uuid.UUID, recipient_id: uuid.UUID, message_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, datetime]]:
    """Record receipt by the recipient. Senders cannot mark their own messages delivered."""
    rows = db.execute(
        update(Message)
        .where(
            Message.id.in_(message_ids),
            Message.conversation_id == conversation_id,
            Message.sender_id != recipient_id,
            Message.delivered_at.is_(None),
            Message.deleted_at.is_(None),
        )
        .values(delivered_at=utcnow())
        .returning(Message.id, Message.delivered_at)
    ).all()
    db.commit()
    return [(row[0], row[1]) for row in rows]


# --- per-user "Clear chat" ------------------------------------------------------


def _membership(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> ConversationMember | None:
    return db.scalar(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user_id
        )
    )


def cleared_through_seq(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> int:
    member = _membership(db, conversation_id, user_id)
    return member.cleared_through_seq if member else 0


def clear_for_user(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """
    Hide everything currently in the conversation from this user only. Nothing is deleted:
    the other member still sees the full history, and new messages appear for both as usual.
    """
    member = _membership(db, conversation_id, user_id)
    assert member is not None
    latest = db.scalar(select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)) or 0
    member.cleared_through_seq = max(member.cleared_through_seq, latest)
    db.commit()
    return member.cleared_through_seq
