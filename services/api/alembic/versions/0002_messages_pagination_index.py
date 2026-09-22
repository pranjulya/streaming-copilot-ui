"""message pagination index

Revision ID: 0002_messages_pagination_index
Revises: 0001_conversations
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_messages_pagination_index"
down_revision: str | None = "0001_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_conversation_created_at_id",
        "messages",
        ["conversation_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created_at_id", table_name="messages")
