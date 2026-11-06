import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from starlette.concurrency import run_in_threadpool

from app.auth.deps import CsrfSessionDep, CurrentSessionDep, DbDep
from app.messaging import service
from app.messaging.connections import manager
from app.messaging.schemas import (
    MAX_BODY_CHARS,
    ClearedOut,
    ConversationListOut,
    ConversationOut,
    DeletedRef,
    DeletionsOut,
    MemberOut,
    MessageOut,
    MessagePageOut,
    ev_cleared,
    ev_deleted,
)

router = APIRouter(prefix="/api", tags=["messaging"])

_NOT_FOUND = "Not found"


def _require_member(db: DbDep, conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    # 404 rather than 403 so non-members learn nothing about which conversations exist.
    if not service.is_member(db, conversation_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)


@router.get("/conversations", response_model=ConversationListOut)
async def list_conversations(current: CurrentSessionDep, db: DbDep) -> ConversationListOut:
    conversation = await run_in_threadpool(service.get_user_conversation, db, current.user.id)
    conversations = []
    if conversation is not None:
        conversations.append(
            ConversationOut(
                id=conversation.id,
                created_at=conversation.created_at,
                members=[
                    MemberOut(
                        id=m.user.id,
                        display_name=m.user.display_name,
                        online=manager.is_online(conversation.id, m.user.id),
                        last_seen_at=m.user.last_seen_at,
                    )
                    for m in conversation.members
                ],
            )
        )
    return ConversationListOut(conversations=conversations, max_body_chars=MAX_BODY_CHARS)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePageOut)
def list_messages(
    conversation_id: uuid.UUID,
    current: CurrentSessionDep,
    db: DbDep,
    before: int | None = Query(default=None, ge=1, description="Return messages with seq < before (older page)"),
    after: int | None = Query(default=None, ge=0, description="Return messages with seq > after (catch-up)"),
    limit: int = Query(default=50, ge=1, le=100),
) -> MessagePageOut:
    if before is not None and after is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use either 'before' or 'after'")
    _require_member(db, conversation_id, current.user.id)
    synced_at = service.sync_timestamp()
    cleared = service.cleared_through_seq(db, conversation_id, current.user.id)
    rows, has_more = service.list_messages(
        db, conversation_id, before=before, after=after, limit=limit, cleared_through=cleared
    )
    return MessagePageOut(messages=[MessageOut.of(m) for m in rows], has_more=has_more, synced_at=synced_at)


@router.get("/conversations/{conversation_id}/deletions", response_model=DeletionsOut)
def list_deletions(
    conversation_id: uuid.UUID,
    current: CurrentSessionDep,
    db: DbDep,
    since: datetime = Query(description="synced_at from a previous messages/deletions response"),
) -> DeletionsOut:
    _require_member(db, conversation_id, current.user.id)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    synced_at = service.sync_timestamp()
    rows = service.list_deletions(db, conversation_id, since)
    return DeletionsOut(
        deleted=[DeletedRef(id=m.id, sender_id=m.sender_id, client_message_id=m.client_message_id) for m in rows],
        synced_at=synced_at,
    )


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(message_id: uuid.UUID, current: CsrfSessionDep, db: DbDep) -> Response:
    """Deletes the message for both users. Only its sender may delete it."""
    result, message = await run_in_threadpool(service.delete_message, db, message_id, current.user.id)
    if result is service.DeleteResult.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    if result is service.DeleteResult.FORBIDDEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the sender can delete a message")
    if result is service.DeleteResult.DELETED and message is not None:
        await manager.broadcast(
            message.conversation_id, ev_deleted(message.id, message.sender_id, message.client_message_id)
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/clear", response_model=ClearedOut)
async def clear_conversation(conversation_id: uuid.UUID, current: CsrfSessionDep, db: DbDep) -> ClearedOut:
    """
    "Clear chat" for the requesting user only. The other member keeps the full history; nothing
    is deleted. The user's other open tabs/devices are told to empty their view.
    """
    user_id = current.user.id
    if not await run_in_threadpool(service.is_member, db, conversation_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    through = await run_in_threadpool(service.clear_for_user, db, conversation_id, user_id)
    await manager.send_to_user(conversation_id, user_id, ev_cleared(through))
    return ClearedOut(cleared_through_seq=through)
