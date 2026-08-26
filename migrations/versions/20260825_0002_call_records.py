"""Store idempotent phone call intake records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "call_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("source_device", sa.String(length=100), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("suggested_project_id", sa.String(length=36), nullable=True),
        sa.Column("project_match_confidence", sa.Float(), nullable=True),
        sa.Column("project_match_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["suggested_project_id"],
            ["project_records.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_id", name="uq_call_tenant_source"),
    )
    op.create_index("ix_call_records_tenant_id", "call_records", ["tenant_id"])
    op.create_index("ix_call_records_content_hash", "call_records", ["content_hash"])
    op.create_index(
        "ix_call_records_suggested_project_id",
        "call_records",
        ["suggested_project_id"],
    )
    op.create_index("ix_call_records_created_at", "call_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_call_records_created_at", table_name="call_records")
    op.drop_index("ix_call_records_suggested_project_id", table_name="call_records")
    op.drop_index("ix_call_records_content_hash", table_name="call_records")
    op.drop_index("ix_call_records_tenant_id", table_name="call_records")
    op.drop_table("call_records")
