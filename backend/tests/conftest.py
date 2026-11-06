import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_ORIGIN = "http://localhost:5173"
PASSWORDS = {"alex": "correct horse battery", "sam": "another long password"}
_TABLES = (
    "messages",
    "conversation_members",
    "conversations",
    "sessions",
    "users",
)


def _configure_test_environment() -> None:
    url = os.environ.get("TEST_DATABASE_URL") or Settings().test_database_url  # type: ignore[call-arg]
    if not url or "test" not in url.rsplit("/", 1)[-1]:
        raise RuntimeError("TEST_DATABASE_URL must point at a database whose name contains 'test'")
    os.environ.update(
        ENVIRONMENT="test",
        DATABASE_URL=url,
        COOKIE_SECURE="false",
        COOKIE_SAMESITE="strict",
        ALLOWED_ORIGINS=FRONTEND_ORIGIN,
        ALLOWED_HOSTS="localhost,testserver",
        LOGIN_RATE_LIMIT_ENABLED="true",
        LOGIN_MAX_FAILURES_PER_USER="5",
        LOGIN_MAX_FAILURES_PER_IP="20",
        LOGIN_WINDOW_SECONDS="900",
        SESSION_TTL_MINUTES="720",
        SESSION_IDLE_MINUTES="60",
        MESSAGE_RATE_LIMIT="10",
        MESSAGE_RATE_WINDOW_SECONDS="60",
        WS_AUTH_RECHECK_SECONDS="0.2",
        MIN_PASSWORD_LENGTH="12",
    )
    get_settings.cache_clear()


os.chdir(BACKEND_DIR)
_configure_test_environment()


@pytest.fixture(scope="session")
def engine():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # exercises the real migrations
    eng = create_engine(get_settings().database_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_state(engine) -> Iterator[None]:
    from app.rate_limit import login_limiter, message_limiter

    from sqlalchemy.exc import OperationalError

    # A WebSocket session watchdog from the previous test may still be finishing a query on a
    # worker thread; TRUNCATE can then deadlock with it. Postgres aborts one side; just retry.
    for attempt in range(5):
        try:
            with engine.begin() as conn:
                conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} CASCADE"))
            break
        except OperationalError:
            if attempt == 4:
                raise
            time.sleep(0.2)
    login_limiter.clear()
    message_limiter.clear()
    yield


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def app(session_factory):
    from app.db import get_db
    from app.main import create_app

    application = create_app()

    def _get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    application.dependency_overrides[get_db] = _get_db
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, base_url="http://localhost", headers={"Origin": FRONTEND_ORIGIN})


@pytest.fixture
def users(db):
    from app.users import create_user

    settings = get_settings()
    return {
        "alex": create_user(db, settings, "alex", "Alex", PASSWORDS["alex"]),
        "sam": create_user(db, settings, "sam", "Sam", PASSWORDS["sam"]),
    }


def login(client: TestClient, username: str = "alex", password: str | None = None):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORDS.get(username, "x") if password is None else password},
    )
