"""simple chat: plain message bodies, replies, per-member clear; drop E2EE key tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03

End-to-end encryption was removed at the owners' request (archive/phase4-e2ee.zip keeps the code).
Any stored duo-e2ee-v1 payloads cannot be read without those keys, so they are wiped here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Encrypted messages are unreadable without the dropped keys; turn them into deletions.
    op.execute(
        "UPDATE messages SET ciphertext = '', encryption_metadata = NULL, deleted_at = COALESCE(deleted_at, now()) "
        "WHERE encryption_version <> 'dev-unencrypted-v0'"
    )
    op.drop_constraint("ck_messages_encryption_version", "messages", type_="check")
    op.drop_constraint("ck_messages_ciphertext_present", "messages", type_="check")
    op.alter_column("messages", "ciphertext", new_column_name="body")
    op.drop_column("messages", "encryption_version")
    op.drop_column("messages", "encryption_metadata")
    op.create_check_constraint("ck_messages_body_present", "messages", "deleted_at IS NOT NULL OR char_length(body) > 0")
    op.add_column(
        "messages",
        sa.Column("reply_to_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "conversation_members",
        sa.Column("cleared_through_seq", sa.BigInteger(), nullable=False, server_default="0"),
    )

    op.drop_table("encrypted_key_envelopes")
    op.drop_table("user_public_keys")


def downgrade() -> None:
    op.create_table(
        "user_public_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_id", sa.String(32), nullable=False),
        sa.Column("encryption_key", sa.Text(), nullable=False),
        sa.Column("signing_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_id", name="uq_user_public_keys_key_id"),
    )
    op.create_index("ix_user_public_keys_user_id", "user_public_keys", ["user_id"])
    op.create_index(
        "uq_user_public_keys_one_active",
        "user_public_keys",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "encrypted_key_envelopes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kdf", sa.String(32), nullable=False),
        sa.Column("kdf_params", JSONB(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_encrypted_key_envelopes_user_id"),
    )
    op.drop_column("conversation_members", "cleared_through_seq")
    op.drop_column("messages", "reply_to_id")
    op.drop_constraint("ck_messages_body_present", "messages", type_="check")
    op.alter_column("messages", "body", new_column_name="ciphertext")
    op.add_column("messages", sa.Column("encryption_metadata", JSONB(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("encryption_version", sa.String(32), nullable=False, server_default="dev-unencrypted-v0"),
    )
    op.alter_column("messages", "encryption_version", server_default=None)
    op.create_check_constraint("ck_messages_encryption_version", "messages", "char_length(encryption_version) > 0")
    op.create_check_constraint(
        "ck_messages_ciphertext_present", "messages", "deleted_at IS NOT NULL OR char_length(ciphertext) > 0"
    )
