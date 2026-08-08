from datetime import datetime
from typing import Optional
import json

from sqlalchemy import (
    String, Integer, Text, DateTime, Boolean, Float,
    ForeignKey, Enum as SAEnum, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    pass


class EntityType(str, enum.Enum):
    CHARACTER = "CHARACTER"
    PLACE = "PLACE"
    PROP = "PROP"
    EVENT = "EVENT"
    DATE = "DATE"
    OTHER = "OTHER"


class Severity(str, enum.Enum):
    HARD = "HARD"   # definitive contradiction (dead/alive, present/absent)
    SOFT = "SOFT"   # description drift, possible inconsistency


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    author: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    entities: Mapped[list["Entity"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    contradictions: Mapped[list["Contradiction"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    document_sync_states: Mapped[list["DocumentSyncState"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    cognee_dataset_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_document_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="chapters")
    aliases: Mapped[list["Alias"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    canonical_name: Mapped[str] = mapped_column(String(256))
    entity_type: Mapped[EntityType] = mapped_column(SAEnum(EntityType))
    first_seen_chapter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapters.id"), nullable=True)
    # JSON-serialized dict of known attributes e.g. {"eye_color": "blue", "status": "alive"}
    attributes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="entities")
    aliases: Mapped[list["Alias"]] = relationship(back_populates="entity", cascade="all, delete-orphan")

    @property
    def attributes(self) -> dict:
        return json.loads(self.attributes_json) if self.attributes_json else {}

    @attributes.setter
    def attributes(self, value: dict):
        self.attributes_json = json.dumps(value)


class Alias(Base):
    __tablename__ = "aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    raw_text: Mapped[str] = mapped_column(String(512))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    entity: Mapped["Entity"] = relationship(back_populates="aliases")
    chapter: Mapped["Chapter"] = relationship(back_populates="aliases")


class Contradiction(Base):
    __tablename__ = "contradictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    chapter_a_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    chapter_b_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entities.id"), nullable=True)
    field: Mapped[str] = mapped_column(String(128))        # e.g. "eye_color"
    value_a: Mapped[str] = mapped_column(Text)             # value in chapter_a
    value_b: Mapped[str] = mapped_column(Text)             # value in chapter_b
    quote_a: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quote_b: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[Severity] = mapped_column(SAEnum(Severity), default=Severity.SOFT)
    # Final arbiter's self-assessed confidence (0.0-1.0) in its CONFIRM/REJECT verdict.
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # "CONFIRM" or "REJECT" - every candidate the proposer/judge pipeline considers is
    # persisted, pass or reject, so the pipeline's reasoning stays inspectable.
    verdict: Mapped[str] = mapped_column(String(16), default="CONFIRM")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="contradictions")


class DocumentSyncState(Base):
    __tablename__ = "document_sync_states"
    __table_args__ = (
        UniqueConstraint("project_id", "document_id", name="uq_document_sync_project_document"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    document_id: Mapped[str] = mapped_column(String(256))
    document_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_synced_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_synced_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_synced_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_checked_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_checked_revision: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_strategy: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    synced_segment_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped["Project"] = relationship(back_populates="document_sync_states")
