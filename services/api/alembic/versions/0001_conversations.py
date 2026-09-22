"""conversations, messages, idempotency_records

Revision ID: 0001_conversations
Revises:
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_conversations"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_user_updated_at_id",
        "conversations",
        ["user_id", sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_conversations_user_archived_at", "conversations", ["user_id", "archived_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column("in_reply_to_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
        sa.CheckConstraint(
            "status IN ('complete','partial','cancelled','failed')", name="ck_messages_status"
        ),
        sa.CheckConstraint(
            "role <> 'user' OR (client_message_id IS NOT NULL AND status = 'complete')",
            name="ck_messages_user_fields",
        ),
        sa.CheckConstraint(
            "role <> 'assistant' OR in_reply_to_id IS NOT NULL",
            name="ck_messages_assistant_fields",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["in_reply_to_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_messages_conversation_client_message_id",
        "messages",
        ["conversation_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_messages_visible_assistant_per_reply",
        "messages",
        ["in_reply_to_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant' AND is_visible"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "operation", "key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("uq_messages_visible_assistant_per_reply", table_name="messages")
    op.drop_index("uq_messages_conversation_client_message_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_archived_at", table_name="conversations")
    op.drop_index("ix_conversations_user_updated_at_id", table_name="conversations")
    op.drop_table("conversations")
