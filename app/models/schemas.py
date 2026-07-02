from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel
from app.models.db import EntityType, Severity


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    title: str
    author: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    title: str
    author: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Chapters ──────────────────────────────────────────────────────────────────

class ChapterIngest(BaseModel):
    number: int
    title: Optional[str] = None
    text: str


class EntityExtracted(BaseModel):
    canonical_name: str
    entity_type: EntityType
    aliases: list[str] = []
    attributes: dict[str, Any] = {}
    resolves_to: str | None = None  # set by LLM when entity matches an existing known entity


class ContradictionOut(BaseModel):
    id: int
    field: str
    value_a: str
    value_b: str
    quote_a: Optional[str]
    quote_b: Optional[str]
    severity: Severity
    chapter_a_id: int
    chapter_b_id: int
    chapter_a_number: Optional[int] = None
    chapter_b_number: Optional[int] = None
    entity_id: Optional[int]
    resolved: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChapterIngestResponse(BaseModel):
    chapter_id: int
    chapter_number: int
    entities_extracted: list[EntityExtracted]
    contradictions_found: list[ContradictionOut]


class ChapterOut(BaseModel):
    id: int
    project_id: int
    number: int
    title: Optional[str]
    ingested_at: datetime

    model_config = {"from_attributes": True}


# ── Recall ────────────────────────────────────────────────────────────────────

class CogneeHit(BaseModel):
    """One RecallResponse item from cognee.recall() — Pydantic object, accessed via .text etc."""
    text: Optional[str] = None
    source: Optional[str] = None     # "graph" | "session" | "trace" | "graph_context"
    score: Optional[float] = None


class RecallRequest(BaseModel):
    focus: Optional[str] = None          # entity name to narrow check
    chapter_ids: Optional[list[int]] = None  # specific chapters; None = all


class RecallResponse(BaseModel):
    contradictions: list[ContradictionOut]
    cognee_hits: list[CogneeHit]          # raw graph retrieval results from cognee.recall()
    checked_chapters: int
    checked_entities: int


# ── Improve ───────────────────────────────────────────────────────────────────

class AliasGroup(BaseModel):
    canonical_name: str
    aliases: list[str]
    confidence: float


class ImproveResponse(BaseModel):
    alias_groups_merged: list[AliasGroup]
    contradictions_resolved: int
    contradictions_new: list[ContradictionOut]


# ── Graph ─────────────────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: int
    label: str
    entity_type: EntityType
    attributes: dict[str, Any]


class GraphEdge(BaseModel):
    source: int
    target: int
    relation: str
    weight: float = 1.0


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ── Timeline ──────────────────────────────────────────────────────────────────

class TimelineEvent(BaseModel):
    entity_id: Optional[int]
    description: str
    chapter_id: int
    chapter_number: int
    order_confidence: float
    raw_date_mention: Optional[str]


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]
    gaps_detected: list[str]
