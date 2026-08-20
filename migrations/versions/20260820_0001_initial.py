"""Initial production schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title", "version", name="uq_document_title_version"),
    )
    op.create_index(
        "ix_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
    )
    op.create_index("ix_knowledge_documents_title", "knowledge_documents", ["title"])

    op.create_table(
        "event_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_event_records_actor", "event_records", ["actor"])
    op.create_index("ix_event_records_created_at", "event_records", ["created_at"])
    op.create_index("ix_event_records_event_type", "event_records", ["event_type"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    op.create_table(
        "model_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_model_name_version"),
    )
    op.create_index("ix_model_artifacts_name", "model_artifacts", ["name"])


def downgrade() -> None:
    op.drop_index("ix_model_artifacts_name", table_name="model_artifacts")
    op.drop_table("model_artifacts")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_event_records_event_type", table_name="event_records")
    op.drop_index("ix_event_records_created_at", table_name="event_records")
    op.drop_index("ix_event_records_actor", table_name="event_records")
    op.drop_table("event_records")
    op.drop_index("ix_knowledge_documents_title", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
