"""Initial production schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "title",
            "version",
            name="uq_document_tenant_title_version",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
    )
    op.create_index("ix_knowledge_documents_title", "knowledge_documents", ["title"])
    op.create_index(
        "ix_knowledge_documents_tenant_id",
        "knowledge_documents",
        ["tenant_id"],
    )

    op.create_table(
        "event_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
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
    op.create_index("ix_event_records_tenant_id", "event_records", ["tenant_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(256) if is_postgres else sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    if is_postgres:
        op.create_index(
            "ix_knowledge_chunks_embedding_hnsw",
            "knowledge_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )

    op.create_table(
        "model_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            "version",
            name="uq_model_tenant_name_version",
        ),
    )
    op.create_index("ix_model_artifacts_name", "model_artifacts", ["name"])
    op.create_index("ix_model_artifacts_tenant_id", "model_artifacts", ["tenant_id"])

    op.create_table(
        "action_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("tool", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_action_tenant_idempotency",
        ),
    )
    op.create_index("ix_action_records_tenant_id", "action_records", ["tenant_id"])
    op.create_index("ix_action_records_tool", "action_records", ["tool"])
    op.create_index("ix_action_records_status", "action_records", ["status"])

    op.create_table(
        "process_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("trigger", sa.String(length=500), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_records_tenant_id", "process_records", ["tenant_id"])
    op.create_index("ix_process_records_trigger", "process_records", ["trigger"])

    op.create_table(
        "process_instance_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("process_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["process_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_process_instance_records_tenant_id",
        "process_instance_records",
        ["tenant_id"],
    )
    op.create_index(
        "ix_process_instance_records_process_id",
        "process_instance_records",
        ["process_id"],
    )
    op.create_index(
        "ix_process_instance_records_status",
        "process_instance_records",
        ["status"],
    )

    op.create_table(
        "handoff_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assigned_to", sa.String(length=128), nullable=True),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("replies", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoff_records_tenant_id", "handoff_records", ["tenant_id"])
    op.create_index("ix_handoff_records_session_id", "handoff_records", ["session_id"])
    op.create_index("ix_handoff_records_status", "handoff_records", ["status"])

    op.create_table(
        "project_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_records_tenant_id", "project_records", ["tenant_id"])
    op.create_index("ix_project_records_status", "project_records", ["status"])

    op.create_table(
        "task_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("deadline", sa.String(length=10), nullable=True),
        sa.Column("assignee", sa.String(length=128), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("checklist", sa.JSON(), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_records_tenant_id", "task_records", ["tenant_id"])
    op.create_index("ix_task_records_project_id", "task_records", ["project_id"])
    op.create_index("ix_task_records_status", "task_records", ["status"])


def downgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    op.drop_index("ix_task_records_status", table_name="task_records")
    op.drop_index("ix_task_records_project_id", table_name="task_records")
    op.drop_index("ix_task_records_tenant_id", table_name="task_records")
    op.drop_table("task_records")
    op.drop_index("ix_project_records_status", table_name="project_records")
    op.drop_index("ix_project_records_tenant_id", table_name="project_records")
    op.drop_table("project_records")
    op.drop_index("ix_handoff_records_status", table_name="handoff_records")
    op.drop_index("ix_handoff_records_session_id", table_name="handoff_records")
    op.drop_index("ix_handoff_records_tenant_id", table_name="handoff_records")
    op.drop_table("handoff_records")
    op.drop_index("ix_process_instance_records_status", table_name="process_instance_records")
    op.drop_index(
        "ix_process_instance_records_process_id",
        table_name="process_instance_records",
    )
    op.drop_index(
        "ix_process_instance_records_tenant_id",
        table_name="process_instance_records",
    )
    op.drop_table("process_instance_records")
    op.drop_index("ix_process_records_trigger", table_name="process_records")
    op.drop_index("ix_process_records_tenant_id", table_name="process_records")
    op.drop_table("process_records")
    op.drop_index("ix_action_records_status", table_name="action_records")
    op.drop_index("ix_action_records_tool", table_name="action_records")
    op.drop_index("ix_action_records_tenant_id", table_name="action_records")
    op.drop_table("action_records")
    op.drop_index("ix_model_artifacts_tenant_id", table_name="model_artifacts")
    op.drop_index("ix_model_artifacts_name", table_name="model_artifacts")
    op.drop_table("model_artifacts")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    if is_postgres:
        op.drop_index(
            "ix_knowledge_chunks_embedding_hnsw",
            table_name="knowledge_chunks",
            postgresql_using="hnsw",
        )
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_event_records_event_type", table_name="event_records")
    op.drop_index("ix_event_records_tenant_id", table_name="event_records")
    op.drop_index("ix_event_records_created_at", table_name="event_records")
    op.drop_index("ix_event_records_actor", table_name="event_records")
    op.drop_table("event_records")
    op.drop_index("ix_knowledge_documents_title", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_tenant_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
