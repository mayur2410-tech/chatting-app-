from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import get_valid_session
from app.config import Settings, get_settings
from app.db import get_db
from app.models import AuthSession, User
from app.security import csrf_matches, csrf_token_for

CSRF_HEADER = "X-CSRF-Token"
_MAX_TOKEN_LENGTH = 128

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class CurrentSession:
    session: AuthSession
    token: str

    @property
    def user(self) -> User:
        return self.session.user


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def read_session_token(request: Request, settings: Settings) -> str | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    return token


def get_current_session(request: Request, db: DbDep, settings: SettingsDep) -> CurrentSession:
    token = read_session_token(request, settings)
    if token is None:
        raise _unauthorized()
    session = get_valid_session(db, token, settings)
    if session is None:
        raise _unauthorized()
    return CurrentSession(session=session, token=token)


def check_csrf(request: Request, token: str, settings: Settings) -> None:
    if not csrf_matches(csrf_token_for(token, settings.secret_key), request.headers.get(CSRF_HEADER)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def require_csrf(
    request: Request,
    current: Annotated[CurrentSession, Depends(get_current_session)],
    settings: SettingsDep,
) -> CurrentSession:
    """Use on every cookie-authenticated, state-changing endpoint."""
    check_csrf(request, current.token, settings)
    return current


CurrentSessionDep = Annotated[CurrentSession, Depends(get_current_session)]
CsrfSessionDep = Annotated[CurrentSession, Depends(require_csrf)]
