"""
Admin CLI for provisioning the two accounts.

    python -m app.cli create-user --username alex --display-name Alex
    python -m app.cli set-password --username alex
    python -m app.cli list-users
    python -m app.cli revoke-sessions --username alex
    python -m app.cli deactivate-user --username alex
    python -m app.cli activate-user --username alex
    python -m app.cli purge-sessions

Passwords are read with a hidden prompt (or from stdin with --password-stdin), never from
command-line arguments, so they don't end up in shell history or process listings.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth.service import purge_dead_sessions, revoke_user_sessions
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import User
from app.users import UserProvisioningError, create_user, get_user, set_active, set_password


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise UserProvisioningError("Passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Duo account administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="Provision one of the two accounts")
    p.add_argument("--username", required=True)
    p.add_argument("--display-name", required=True)
    p.add_argument("--password-stdin", action="store_true")

    p = sub.add_parser("set-password", help="Change a password and sign out all of that user's sessions")
    p.add_argument("--username", required=True)
    p.add_argument("--password-stdin", action="store_true")

    for name in ("revoke-sessions", "deactivate-user", "activate-user"):
        sub.add_parser(name).add_argument("--username", required=True)

    sub.add_parser("list-users")
    sub.add_parser("purge-sessions", help="Delete expired and revoked session rows")

    args = parser.parse_args(argv)
    settings = get_settings()

    with get_sessionmaker()() as db:
        try:
            match args.command:
                case "create-user":
                    user = create_user(db, settings, args.username, args.display_name, _read_password(args.password_stdin))
                    print(f"Created user '{user.username}'")
                case "set-password":
                    set_password(db, args.username, _read_password(args.password_stdin))
                    print("Password updated; existing sessions revoked")
                case "revoke-sessions":
                    count = revoke_user_sessions(db, get_user(db, args.username).id)
                    print(f"Revoked {count} session(s)")
                case "deactivate-user":
                    set_active(db, settings, args.username, False)
                    print("User deactivated; sessions revoked")
                case "activate-user":
                    set_active(db, settings, args.username, True)
                    print("User activated")
                case "list-users":
                    for u in db.scalars(select(User).order_by(User.created_at)):
                        print(f"{u.username:<32} {u.display_name:<24} {'active' if u.is_active else 'inactive'}")
                case "purge-sessions":
                    print(f"Deleted {purge_dead_sessions(db)} session row(s)")
        except UserProvisioningError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
