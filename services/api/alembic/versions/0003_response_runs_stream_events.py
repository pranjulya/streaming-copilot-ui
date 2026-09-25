"""response runs and stream events

Revision ID: 0003_response_runs_stream_events
Revises: 0002_messages_pagination_index
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_response_runs_stream_events"
down_revision: str | None = "0002_messages_pagination_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("uq_conversations_id_user_id", "conversations", ["id", "user_id"], unique=True)

    op.create_table(
        "response_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("last_sequence", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_instance_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("diagnostic_id", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued','streaming','cancelling','completed','cancelled','failed')",
            name="ck_response_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["conversations.id", "conversations.user_id"],
            name="fk_response_runs_conversation_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["messages.id"],
            name="fk_runs_assistant_message",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"], ["messages.id"], name="fk_runs_user_message", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_response_runs_one_active",
        "response_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','streaming','cancelling')"),
    )
    op.create_index(
        "ix_response_runs_user_active",
        "response_runs",
        ["user_id"],
        postgresql_where=sa.text("status IN ('queued','streaming','cancelling')"),
    )

    op.create_table(
        "stream_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["response_runs.id"], name="fk_stream_events_run", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_index("uq_stream_events_event_id", "stream_events", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_stream_events_event_id", table_name="stream_events")
    op.drop_table("stream_events")
    op.drop_index("ix_response_runs_user_active", table_name="response_runs")
    op.drop_index("uq_response_runs_one_active", table_name="response_runs")
    op.drop_table("response_runs")
    op.drop_index("uq_conversations_id_user_id", table_name="conversations")
