"""Add standalone campaign lead registry."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("campaign_code", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("qualification_score", sa.Integer(), nullable=False),
        sa.Column("next_question", sa.Text(), nullable=True),
        sa.Column("handoff_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["handoff_id"], ["handoff_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "campaign_code",
            "external_id",
            name="uq_lead_tenant_campaign_external",
        ),
    )
    op.create_index("ix_lead_records_tenant_id", "lead_records", ["tenant_id"])
    op.create_index("ix_lead_records_campaign_code", "lead_records", ["campaign_code"])
    op.create_index("ix_lead_records_session_id", "lead_records", ["session_id"])
    op.create_index("ix_lead_records_status", "lead_records", ["status"])
    op.create_index("ix_lead_records_priority", "lead_records", ["priority"])
    op.create_index("ix_lead_records_handoff_id", "lead_records", ["handoff_id"])
    op.create_index("ix_lead_records_created_at", "lead_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_records_created_at", table_name="lead_records")
    op.drop_index("ix_lead_records_handoff_id", table_name="lead_records")
    op.drop_index("ix_lead_records_priority", table_name="lead_records")
    op.drop_index("ix_lead_records_status", table_name="lead_records")
    op.drop_index("ix_lead_records_session_id", table_name="lead_records")
    op.drop_index("ix_lead_records_campaign_code", table_name="lead_records")
    op.drop_index("ix_lead_records_tenant_id", table_name="lead_records")
    op.drop_table("lead_records")
