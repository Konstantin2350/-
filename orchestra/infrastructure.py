import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    __table_args__ = (UniqueConstraint("title", "version", name="uq_document_title_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
    embedding: Mapped[list[float]] = mapped_column(JSON)


class EventRecord(Base):
    __tablename__ = "event_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(200), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
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
    ) -> bool:
        async with self.sessions() as session:
            session.add(
                EventRecord(
                    id=str(uuid4()),
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

    async def recent_events(self, limit: int = 1_000) -> list[EventRecord]:
        async with self.sessions() as session:
            result = await session.execute(
                select(EventRecord)
                .order_by(EventRecord.created_at.desc())
                .limit(min(limit, 10_000))
            )
            return list(result.scalars())

    async def save_model(
        self,
        name: str,
        parameters: dict[str, Any],
        metrics: dict[str, Any],
    ) -> ModelArtifact:
        async with self.sessions() as session:
            latest_result = await session.execute(
                select(ModelArtifact.version)
                .where(ModelArtifact.name == name)
                .order_by(ModelArtifact.version.desc())
                .limit(1)
            )
            model = ModelArtifact(
                id=str(uuid4()),
                name=name,
                version=(latest_result.scalar_one_or_none() or 0) + 1,
                parameters=parameters,
                metrics=metrics,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return model

    async def active_model(self, name: str) -> ModelArtifact | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ModelArtifact)
                .where(ModelArtifact.name == name)
                .order_by(ModelArtifact.version.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def next_document_version(self, title: str) -> int:
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeDocument.version)
                .where(KnowledgeDocument.title == title)
                .order_by(KnowledgeDocument.version.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            return (latest or 0) + 1

    async def existing_document(
        self, title: str, content_hash: str
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
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            id=str(uuid4()),
            title=title,
            source_name=source_name,
            version=await self.next_document_version(title),
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
        self,
    ) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
        async with self.sessions() as session:
            result = await session.execute(
                select(KnowledgeChunk, KnowledgeDocument).join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
            )
            return list(result.all())


class ConversationMemory:
    """Redis session memory with a safe in-process fallback for local operation."""

    def __init__(self, settings: Settings) -> None:
        self.ttl = settings.memory_ttl_seconds
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
                pass
        self.local[session_id].append(item)
        self.local[session_id] = self.local[session_id][-50:]

    async def history(self, session_id: str) -> list[dict[str, str]]:
        if self.redis:
            try:
                values = await self.redis.lrange(f"orchestra:conversation:{session_id}", -50, -1)
                if values:
                    return [json.loads(value) for value in values]
            except Exception:
                pass
        return list(self.local[session_id])

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()


def as_uuid(value: str) -> UUID:
    return UUID(value)
