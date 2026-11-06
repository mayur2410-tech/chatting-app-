import logging

from anyio.from_thread import run as run_in_event_loop
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.auth.deps import CurrentSessionDep, DbDep, SettingsDep, check_csrf, read_session_token
from app.auth.schemas import LoginIn, SessionOut, UserOut
from app.auth.service import (
    authenticate,
    create_session,
    get_valid_session,
    normalize_username,
    revoke_session,
    revoke_token,
)
from app.config import Settings
from app.messaging.connections import manager as connection_manager
from app.models import AuthSession, User
from app.rate_limit import login_limiter
from app.security import csrf_token_for

logger = logging.getLogger("duo.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid username or password"
TOO_MANY_ATTEMPTS = "Too many attempts. Try again later."


def _session_out(user: User, session: AuthSession, token: str, settings: Settings) -> SessionOut:
    return SessionOut(
        user=UserOut(id=user.id, username=user.username, display_name=user.display_name),
        csrf_token=csrf_token_for(token, settings.secret_key),
        expires_at=session.expires_at,
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    # No Max-Age/Expires: a browser-session cookie, discarded when the browser closes. The server
    # still enforces SESSION_TTL_MINUTES and SESSION_IDLE_MINUTES on its side.
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _client_ip(request: Request) -> str:
    # Behind Caddy, uvicorn's --proxy-headers populates request.client from X-Forwarded-For.
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep) -> SessionOut:
    user_key = f"user:{normalize_username(body.username)}"
    ip_key = f"ip:{_client_ip(request)}"
    window = settings.login_window_seconds
    limited = settings.login_rate_limit_enabled

    if limited:
        retry_after = max(
            login_limiter.retry_after(user_key, settings.login_max_failures_per_user, window),
            login_limiter.retry_after(ip_key, settings.login_max_failures_per_ip, window),
        )
        if retry_after:
            logger.warning("Login rate limit hit")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=TOO_MANY_ATTEMPTS,
                headers={"Retry-After": str(retry_after)},
            )

    user = authenticate(db, body.username, body.password)
    if user is None:
        if limited:
            login_limiter.record(user_key)
            login_limiter.record(ip_key)
        logger.info("Login failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    if limited:
        login_limiter.reset(user_key)

    # Prevent session fixation: any session the browser already presented is retired.
    previous = read_session_token(request, settings)
    if previous:
        revoke_token(db, previous)

    token, session = create_session(db, user, settings)
    _set_session_cookie(response, token, settings)
    logger.info("Login succeeded")
    return _session_out(user, session, token, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DbDep, settings: SettingsDep) -> Response:
    """Idempotent. A live session must present its CSRF token; a dead one just has its cookie cleared."""
    token = read_session_token(request, settings)
    if token:
        session = get_valid_session(db, token, settings)
        if session is not None:
            check_csrf(request, token, settings)
            revoke_session(db, session)
            # Close this session's open chat sockets now rather than at the next watchdog check.
            # (This sync endpoint runs in a worker thread; hop onto the event loop to do it.)
            run_in_event_loop(connection_manager.end_session, session.id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=SessionOut)
def me(current: CurrentSessionDep, settings: SettingsDep) -> SessionOut:
    return _session_out(current.user, current.session, current.token, settings)
