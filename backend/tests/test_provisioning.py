import io

import pytest

from app import cli
from app.config import get_settings
from app.security import hash_password, needs_rehash, verify_password
from app.users import UserProvisioningError, create_user


def test_passwords_hashed_with_argon2id(db, users):
    assert users["alex"].password_hash.startswith("$argon2id$")
    assert not needs_rehash(users["alex"].password_hash)


def test_verify_password():
    h = hash_password("a sufficiently long password")
    assert verify_password(h, "a sufficiently long password")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize(
    ("username", "display", "password"),
    [
        ("ab", "Ab", "long enough password"),  # username too short
        ("bad name", "Bad", "long enough password"),  # invalid chars
        ("valid", "", "long enough password"),  # empty display name
        ("valid", "Valid", "short"),  # weak password
    ],
)
def test_create_user_validation(db, username, display, password):
    with pytest.raises(UserProvisioningError):
        create_user(db, get_settings(), username, display, password)


def test_duplicate_username_rejected(db, users):
    with pytest.raises(UserProvisioningError):
        create_user(db, get_settings(), "ALEX", "Alex 2", "another long password")


def test_cli_create_user_from_stdin(db, monkeypatch, capsys, session_factory):
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.stdin", io.StringIO("cli provided password\n"))
    assert cli.main(["create-user", "--username", "jo", "--display-name", "Jo", "--password-stdin"]) == 1  # too short name

    monkeypatch.setattr("sys.stdin", io.StringIO("cli provided password\n"))
    assert cli.main(["create-user", "--username", "jordan", "--display-name", "Jordan", "--password-stdin"]) == 0
    out = capsys.readouterr().out
    assert "Created user 'jordan'" in out
    assert "cli provided password" not in out


def test_cli_refuses_third_user(users, monkeypatch, capsys, session_factory):
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.stdin", io.StringIO("third long password\n"))
    assert cli.main(["create-user", "--username", "third", "--display-name", "T", "--password-stdin"]) == 1
    assert "at most 2" in capsys.readouterr().err
