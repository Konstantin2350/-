import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from redis.asyncio import Redis
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from orchestra.config import Settings


class Base(DeclarativeBase):
    pass


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "title", "version", name="uq_document_tenant_title_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    source_name: Mapped[str] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(256).with_variant(JSON(), "sqlite"))


class EventRecord(Base):
    __tablename__ = "event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(200), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_model_tenant_name_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ActionRecord(Base):
    __tablename__ = "action_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_tenant_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    tool: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    requires_confirmation: Mapped[bool]
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProcessRecord(Base):
    __tablename__ = "process_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(300))
    trigger: Mapped[str] = mapped_column(String(500), index=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ProcessInstanceRecord(Base):
    __tablename__ = "process_instance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    process_id: Mapped[str] = mapped_column(
        ForeignKey("process_records.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    current_step: Mapped[int] = mapped_column(default=0)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class HandoffRecord(Base):
    __tablename__ = "handoff_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    history: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    replies: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class LeadRecord(Base):
    __tablename__ = "lead_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "campaign_code",
            "external_id",
            name="uq_lead_tenant_campaign_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    campaign_code: Mapped[str] = mapped_column(String(100), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    answers: Mapped[dict[str, str]] = mapped_column(JSON)
    history: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), index=True)
    priority: Mapped[str] = mapped_column(String(20), index=True)
    qualification_score: Mapped[int] = mapped_column(Integer)
    next_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_id: Mapped[str | None] = mapped_column(
        ForeignKey("handoff_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProjectRecord(Base):
    __tablename__ = "project_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class TaskRecord(Base):
    __tablename__ = "task_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    checklist: Mapped[list[str]] = mapped_column(JSON)
    risk_flags: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def append_event(
        self,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        external_id: str | None = None,
        tenant_id: str = "default",
    ) -> bool:
        async with self.sessions() as session:
            session.add(
                EventRecord(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    event_type=event_type,
                    actor=actor,
                    external_id=external_id,
                    payload=payload,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
        return True

    async def recent_events(
        self, limit: int = 1_000, tenant_id: str = "default"
    ) -> list[EventRecord]:
        async with self.sessions() as session:
            result = await session.execute(
                select(EventRecord)
                .where(EventRecord.tenant_id == tenant_id)
                .order_by(EventRecord.created_at.desc())
                .limit(min(limit, 10_000))
            )
            return list(result.scalars())

    async def save_model(
        self,
        name: str,
        parameters: dict[str, Any],
        metrics: dict[str, Any],
        tenant_id: str = "default",
    ) -> ModelArtifact:
        async with self.sessions() as session:
            latest_result = await session.execute(
                select(ModelArtifact.version)
                .where(
                    ModelArtifact.name == name,
                    ModelArtifact.tenant_id == tenant_id,
                )
                .order_by(ModelArtifact.version.desc())
                .limit(1)
            )
            model = ModelArtifact(
                id=str(uuid4()),
                tenant_id=tenant_id,
                name=name,
                version=(latest_result.scalar_one_or_none() or 0) + 1,
                parameters=parameters,
                metrics=metrics,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def active_model(self, name: str, tenant_id: str = "default") -> ModelArtifact | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ModelArtifact)
                .where(
                    ModelArtifact.name == name,
                    ModelArtifact.tenant_id == tenant_id,
                )
                .order_by(ModelArtifact.version.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def next_document_version(self, title: str, tenant_id: str = "default") -> int:
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeDocument.version)
                .where(
                    KnowledgeDocument.title == title,
                    KnowledgeDocument.tenant_id == tenant_id,
                )
                .order_by(KnowledgeDocument.version.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            return (latest or 0) + 1

    async def existing_document(
        self, title: str, content_hash: str, tenant_id: str = "default"
    ) -> tuple[KnowledgeDocument, int] | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeDocument, func.count(KnowledgeChunk.id))
                .outerjoin(
                    KnowledgeChunk,
                    KnowledgeChunk.document_id == KnowledgeDocument.id,
                )
                .where(
                    KnowledgeDocument.title == title,
                    KnowledgeDocument.content_hash == content_hash,
                    KnowledgeDocument.tenant_id == tenant_id,
                )
                .group_by(KnowledgeDocument.id)
                .order_by(KnowledgeDocument.version.desc())
                .limit(1)
            )
            return result.one_or_none()

    async def save_document(
        self,
        title: str,
        source_name: str,
        content_hash: str,
        chunks: list[tuple[str, list[float]]],
        tenant_id: str = "default",
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            id=str(uuid4()),
            tenant_id=tenant_id,
            title=title,
            source_name=source_name,
            version=await self.next_document_version(title, tenant_id),
            content_hash=content_hash,
        )
        async with self.sessions() as session:
            session.add(document)
            await session.flush()
            session.add_all(
                KnowledgeChunk(
                    document_id=document.id,
                    position=index,
                    text=text,
                    embedding=embedding,
                )
                for index, (text, embedding) in enumerate(chunks)
            )
            await session.commit()
            await session.refresh(document)
        return document

    async def all_chunks(
        self, tenant_id: str = "default"
    ) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .where(KnowledgeDocument.tenant_id == tenant_id)
            )
            return list(result.all())

    async def search_chunks(
        self,
        tenant_id: str,
        embedding: list[float],
        limit: int,
    ) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
        if self.engine.dialect.name != "postgresql":
            return await self.all_chunks(tenant_id)
        latest = (
            select(
                KnowledgeDocument.tenant_id.label("tenant_id"),
                KnowledgeDocument.title.label("title"),
                func.max(KnowledgeDocument.version).label("version"),
            )
            .where(KnowledgeDocument.tenant_id == tenant_id)
            .group_by(KnowledgeDocument.tenant_id, KnowledgeDocument.title)
            .subquery()
        )
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .join(
                    latest,
                    and_(
                        latest.c.tenant_id == KnowledgeDocument.tenant_id,
                        latest.c.title == KnowledgeDocument.title,
                        latest.c.version == KnowledgeDocument.version,
                    ),
                )
                .where(KnowledgeDocument.tenant_id == tenant_id)
                .order_by(KnowledgeChunk.embedding.cosine_distance(embedding))
                .limit(min(max(limit * 8, 40), 500))
            )
            return list(result.all())

    async def create_action(
        self,
        tenant_id: str,
        actor: str,
        tool: str,
        payload: dict[str, Any],
        requires_confirmation: bool = True,
        idempotency_key: str | None = None,
    ) -> ActionRecord:
        action = ActionRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            actor=actor,
            tool=tool,
            status="proposed" if requires_confirmation else "confirmed",
            payload=payload,
            requires_confirmation=requires_confirmation,
            idempotency_key=idempotency_key,
        )
        async with self.sessions() as session:
            session.add(action)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if not idempotency_key:
                    raise
                result = await session.execute(
                    select(ActionRecord).where(
                        ActionRecord.tenant_id == tenant_id,
                        ActionRecord.idempotency_key == idempotency_key,
                    )
                )
                return result.scalar_one()
            await session.refresh(action)
            return action

    async def get_action(self, action_id: str, tenant_id: str) -> ActionRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ActionRecord).where(
                    ActionRecord.id == action_id,
                    ActionRecord.tenant_id == tenant_id,
                )
            )
            return result.scalar_one_or_none()

    async def list_actions(self, tenant_id: str, status: str | None = None) -> list[ActionRecord]:
        async with self.sessions() as session:
            query = select(ActionRecord).where(ActionRecord.tenant_id == tenant_id)
            if status:
                query = query.where(ActionRecord.status == status)
            result = await session.execute(
                query.order_by(ActionRecord.created_at.desc()).limit(500)
            )
            return list(result.scalars())

    async def update_action(
        self, action_id: str, tenant_id: str, **values: Any
    ) -> ActionRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ActionRecord).where(
                    ActionRecord.id == action_id,
                    ActionRecord.tenant_id == tenant_id,
                )
            )
            action = result.scalar_one_or_none()
            if not action:
                return None
            for key, value in values.items():
                setattr(action, key, value)
            action.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(action)
            return action

    async def save_process(self, tenant_id: str, definition: dict[str, Any]) -> ProcessRecord:
        process = ProcessRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            name=definition["name"],
            trigger=definition["trigger"],
            definition=definition,
            active=True,
        )
        async with self.sessions() as session:
            session.add(process)
            await session.commit()
            await session.refresh(process)
            return process

    async def get_process(self, process_id: str, tenant_id: str) -> ProcessRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ProcessRecord).where(
                    ProcessRecord.id == process_id,
                    ProcessRecord.tenant_id == tenant_id,
                )
            )
            return result.scalar_one_or_none()

    async def processes_for_trigger(self, trigger: str, tenant_id: str) -> list[ProcessRecord]:
        async with self.sessions() as session:
            result = await session.execute(
                select(ProcessRecord).where(
                    ProcessRecord.tenant_id == tenant_id,
                    ProcessRecord.active.is_(True),
                    ProcessRecord.trigger == trigger,
                )
            )
            return list(result.scalars())

    async def create_process_instance(
        self, process_id: str, tenant_id: str, context: dict[str, Any]
    ) -> ProcessInstanceRecord:
        instance = ProcessInstanceRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            process_id=process_id,
            status="running",
            current_step=0,
            context=context,
            history=[],
        )
        async with self.sessions() as session:
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def get_process_instance(
        self, instance_id: str, tenant_id: str
    ) -> ProcessInstanceRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ProcessInstanceRecord).where(
                    ProcessInstanceRecord.id == instance_id,
                    ProcessInstanceRecord.tenant_id == tenant_id,
                )
            )
            return result.scalar_one_or_none()

    async def update_process_instance(
        self, instance_id: str, tenant_id: str, **values: Any
    ) -> ProcessInstanceRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ProcessInstanceRecord).where(
                    ProcessInstanceRecord.id == instance_id,
                    ProcessInstanceRecord.tenant_id == tenant_id,
                )
            )
            instance = result.scalar_one_or_none()
            if not instance:
                return None
            for key, value in values.items():
                setattr(instance, key, value)
            instance.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def create_handoff(
        self,
        tenant_id: str,
        session_id: str,
        user_id: str,
        channel: str,
        reason: str,
        history: list[dict[str, str]],
    ) -> HandoffRecord:
        handoff = HandoffRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            status="queued",
            reason=reason,
            history=history,
            replies=[],
        )
        async with self.sessions() as session:
            session.add(handoff)
            await session.commit()
            await session.refresh(handoff)
            return handoff

    async def list_handoffs(self, tenant_id: str, status: str | None = None) -> list[HandoffRecord]:
        async with self.sessions() as session:
            query = select(HandoffRecord).where(HandoffRecord.tenant_id == tenant_id)
            if status:
                query = query.where(HandoffRecord.status == status)
            result = await session.execute(
                query.order_by(HandoffRecord.created_at.desc()).limit(500)
            )
            return list(result.scalars())

    async def update_handoff(
        self, handoff_id: str, tenant_id: str, **values: Any
    ) -> HandoffRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(HandoffRecord).where(
                    HandoffRecord.id == handoff_id,
                    HandoffRecord.tenant_id == tenant_id,
                )
            )
            handoff = result.scalar_one_or_none()
            if not handoff:
                return None
            for key, value in values.items():
                setattr(handoff, key, value)
            handoff.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(handoff)
            return handoff

    async def upsert_lead(
        self,
        tenant_id: str,
        campaign_code: str,
        external_id: str,
        values: dict[str, Any],
        message: str,
    ) -> tuple[LeadRecord, bool]:
        async with self.sessions() as session:
            result = await session.execute(
                select(LeadRecord).where(
                    LeadRecord.tenant_id == tenant_id,
                    LeadRecord.campaign_code == campaign_code,
                    LeadRecord.external_id == external_id,
                )
            )
            lead = result.scalar_one_or_none()
            created = lead is None
            if lead is None:
                lead = LeadRecord(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    campaign_code=campaign_code,
                    external_id=external_id,
                    history=[{"role": "client", "content": message}],
                    **values,
                )
                session.add(lead)
            else:
                history = list(lead.history)
                if not history or history[-1] != {"role": "client", "content": message}:
                    history.append({"role": "client", "content": message})
                values["history"] = history[-100:]
                for key, value in values.items():
                    setattr(lead, key, value)
                lead.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(lead)
            return lead, created

    async def get_lead(self, lead_id: str, tenant_id: str) -> LeadRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(LeadRecord).where(
                    LeadRecord.id == lead_id,
                    LeadRecord.tenant_id == tenant_id,
                )
            )
            return result.scalar_one_or_none()

    async def find_lead(
        self, tenant_id: str, campaign_code: str, external_id: str
    ) -> LeadRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(LeadRecord).where(
                    LeadRecord.tenant_id == tenant_id,
                    LeadRecord.campaign_code == campaign_code,
                    LeadRecord.external_id == external_id,
                )
            )
            return result.scalar_one_or_none()

    async def list_leads(
        self,
        tenant_id: str,
        campaign_code: str | None = None,
        status: str | None = None,
    ) -> list[LeadRecord]:
        async with self.sessions() as session:
            query = select(LeadRecord).where(LeadRecord.tenant_id == tenant_id)
            if campaign_code:
                query = query.where(LeadRecord.campaign_code == campaign_code)
            if status:
                query = query.where(LeadRecord.status == status)
            result = await session.execute(
                query.order_by(LeadRecord.created_at.desc()).limit(2_000)
            )
            return list(result.scalars())

    async def update_lead(
        self, lead_id: str, tenant_id: str, values: dict[str, Any]
    ) -> LeadRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(LeadRecord).where(
                    LeadRecord.id == lead_id,
                    LeadRecord.tenant_id == tenant_id,
                )
            )
            lead = result.scalar_one_or_none()
            if not lead:
                return None
            for key, value in values.items():
                if value is not None:
                    setattr(lead, key, value)
            lead.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(lead)
            return lead

    async def create_project(self, tenant_id: str, name: str, description: str) -> ProjectRecord:
        project = ProjectRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            status="active",
        )
        async with self.sessions() as session:
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project

    async def list_projects(self, tenant_id: str) -> list[ProjectRecord]:
        async with self.sessions() as session:
            result = await session.execute(
                select(ProjectRecord)
                .where(ProjectRecord.tenant_id == tenant_id)
                .order_by(ProjectRecord.created_at.desc())
                .limit(500)
            )
            return list(result.scalars())

    async def create_task(self, tenant_id: str, values: dict[str, Any]) -> TaskRecord:
        task = TaskRecord(
            id=str(uuid4()),
            tenant_id=tenant_id,
            **values,
        )
        async with self.sessions() as session:
            if task.project_id:
                project = await session.get(ProjectRecord, task.project_id)
                if not project or project.tenant_id != tenant_id:
                    raise ValueError("Project not found")
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task

    async def list_tasks(self, tenant_id: str, project_id: str | None = None) -> list[TaskRecord]:
        async with self.sessions() as session:
            query = select(TaskRecord).where(TaskRecord.tenant_id == tenant_id)
            if project_id:
                query = query.where(TaskRecord.project_id == project_id)
            result = await session.execute(
                query.order_by(TaskRecord.created_at.desc()).limit(2_000)
            )
            return list(result.scalars())

    async def update_task(
        self, task_id: str, tenant_id: str, values: dict[str, Any]
    ) -> TaskRecord | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(TaskRecord).where(
                    TaskRecord.id == task_id,
                    TaskRecord.tenant_id == tenant_id,
                )
            )
            task = result.scalar_one_or_none()
            if not task:
                return None
            for key, value in values.items():
                if value is not None:
                    setattr(task, key, value)
            task.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(task)
            return task


class ConversationMemory:
    """Redis session memory with a safe in-process fallback for local operation."""

    def __init__(self, settings: Settings) -> None:
        self.ttl = settings.memory_ttl_seconds
        self.production = settings.environment == "production"
        self.redis = Redis.from_url(settings.redis_url) if settings.redis_url else None
        self.local: dict[str, list[dict[str, str]]] = defaultdict(list)

    async def add(self, session_id: str, role: str, content: str) -> None:
        item = {"role": role, "content": content}
        if self.redis:
            key = f"orchestra:conversation:{session_id}"
            try:
                await self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
                await self.redis.expire(key, self.ttl)
                return
            except Exception:
                if self.production:
                    raise
        self.local[session_id].append(item)
        self.local[session_id] = self.local[session_id][-50:]

    async def history(self, session_id: str) -> list[dict[str, str]]:
        if self.redis:
            try:
                values = await self.redis.lrange(f"orchestra:conversation:{session_id}", -50, -1)
                if values:
                    return [json.loads(value) for value in values]
            except Exception:
                if self.production:
                    raise
        return list(self.local[session_id])

    async def ping(self) -> bool:
        if not self.redis:
            return not self.production
        return bool(await self.redis.ping())

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()


def as_uuid(value: str) -> UUID:
    return UUID(value)
