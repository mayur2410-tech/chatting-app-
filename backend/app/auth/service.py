from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import AuthSession, User
from app.security import hash_password, hash_token, needs_rehash, new_session_token, verify_password

# Avoid a DB write on every request: only bump last_seen_at when it is older than this.
_TOUCH_INTERVAL = timedelta(seconds=60)


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    usable = user is not None and user.is_active
    # Always run a full Argon2 verification so unknown and known usernames take the same time.
    if not verify_password(user.password_hash if usable else None, password) or user is None:
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    return user


def create_session(db: Session, user: User, settings: Settings) -> tuple[str, AuthSession]:
    token = new_session_token()
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.session_ttl_minutes),
    )
    db.add(session)
    db.commit()
    return token, session


def get_valid_session(db: Session, token: str, settings: Settings) -> AuthSession | None:
    session = db.scalar(
        select(AuthSession).options(joinedload(AuthSession.user)).where(AuthSession.token_hash == hash_token(token))
    )
    if session is None:
        return None
    now = utcnow()
    if (
        session.revoked_at is not None
        or now >= session.expires_at
        or now - session.last_seen_at >= timedelta(minutes=settings.session_idle_minutes)
        or not session.user.is_active
    ):
        return None
    if now - session.last_seen_at >= _TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return session


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = utcnow()
    db.commit()


def revoke_token(db: Session, token: str) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()


def revoke_user_sessions(db: Session, user_id: object) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
    return result.rowcount


def purge_dead_sessions(db: Session) -> int:
    """Delete expired and revoked session rows; they carry no value once unusable."""
    result = db.execute(
        delete(AuthSession).where(or_(AuthSession.expires_at < utcnow(), AuthSession.revoked_at.is_not(None)))
    )
    db.commit()
    return result.rowcount
