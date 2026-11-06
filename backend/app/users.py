"""User provisioning. Only reachable from the admin CLI — there is no HTTP endpoint for any of this."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import normalize_username, revoke_user_sessions
from app.config import Settings, get_settings
from app.models import User
from app.security import hash_password

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


class UserProvisioningError(Exception):
    pass


def validate_password(password: str) -> None:
    minimum = get_settings().min_password_length
    if len(password) < minimum:
        raise UserProvisioningError(f"Password must be at least {minimum} characters")
    if len(password) > 256:
        raise UserProvisioningError("Password must be at most 256 characters")


def create_user(db: Session, settings: Settings, username: str, display_name: str, password: str) -> User:
    username = normalize_username(username)
    display_name = display_name.strip()
    if not USERNAME_RE.fullmatch(username):
        raise UserProvisioningError("Username must be 3–32 chars: lowercase letters, digits, '.', '_' or '-'")
    if not 1 <= len(display_name) <= 64:
        raise UserProvisioningError("Display name must be 1–64 characters")
    validate_password(password)

    active = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    if active >= settings.max_users:
        raise UserProvisioningError(f"This deployment allows at most {settings.max_users} active users")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise UserProvisioningError("That username already exists")

    user = User(username=username, display_name=display_name, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    return user


def get_user(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        raise UserProvisioningError("No such user")
    return user


def set_password(db: Session, username: str, password: str) -> None:
    validate_password(password)
    user = get_user(db, username)
    user.password_hash = hash_password(password)
    db.commit()
    revoke_user_sessions(db, user.id)


def set_active(db: Session, settings: Settings, username: str, active: bool) -> None:
    user = get_user(db, username)
    if active and not user.is_active:
        count = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
        if count >= settings.max_users:
            raise UserProvisioningError(f"This deployment allows at most {settings.max_users} active users")
    user.is_active = active
    db.commit()
    if not active:
        revoke_user_sessions(db, user.id)
