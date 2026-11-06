import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id, OWASP-recommended baseline (m=19 MiB, t=2, p=1) raised to 64 MiB / t=3.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=1, hash_len=32, salt_len=16, type=Type.ID)

# Verified against when a username does not exist, so failed logins take the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    """256 bits of randomness, URL-safe. Sent only in the HttpOnly cookie."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str, secret_key: str) -> str:
    """CSRF token bound to the session: HMAC(secret, session token). Nothing extra is stored."""
    return hmac.new(secret_key.encode(), b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def csrf_matches(expected: str, provided: str | None) -> bool:
    return provided is not None and hmac.compare_digest(expected, provided)
