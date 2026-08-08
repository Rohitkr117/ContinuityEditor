from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.db import EntityType, Severity


class ProjectCreate(BaseModel):
    title: str
    author: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    title: str
    author: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ChapterIngest(BaseModel):
    number: int
    title: Optional[str] = None
    text: str


class EntityExtracted(BaseModel):
    canonical_name: str
    entity_type: EntityType
    aliases: list[str] = []
    attributes: dict[str, Any] = {}
    resolves_to: str | None = None


class ContradictionOut(BaseModel):
    id: int
    field: str
    value_a: str
    value_b: str
    quote_a: Optional[str]
    quote_b: Optional[str]
    reason: Optional[str] = None
    severity: Severity
    confidence: float = 0.5
    verdict: str = "CONFIRM"
    chapter_a_id: int
    chapter_b_id: int
    chapter_a_number: Optional[int] = None
    chapter_b_number: Optional[int] = None
    entity_id: Optional[int]
    entity_name: Optional[str] = None
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


class CogneeHit(BaseModel):
    text: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None


class RecallRequest(BaseModel):
    focus: Optional[str] = None
    chapter_ids: Optional[list[int]] = None


class RecallResponse(BaseModel):
    contradictions: list[ContradictionOut]
    cognee_hits: list[CogneeHit]
    checked_chapters: int
    checked_entities: int


class AliasGroup(BaseModel):
    canonical_name: str
    aliases: list[str]
    confidence: float


class ImproveResponse(BaseModel):
    alias_groups_merged: list[AliasGroup]
    contradictions_resolved: int
    contradictions_new: list[ContradictionOut]


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


class ExtensionStatusResponse(BaseModel):
    project_id: int
    project_title: str
    document_id: str
    document_title: Optional[str] = None
    sync_state: str
    has_synced_content: bool
    last_synced_hash: Optional[str] = None
    last_synced_revision: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_checked_hash: Optional[str] = None
    last_checked_revision: Optional[str] = None
    last_issue_count: int = 0
    synced_segment_count: int = 0


class ExtensionDocumentRequest(BaseModel):
    document_id: str
    document_title: Optional[str] = None
    document_text: str
    document_revision: Optional[str] = None


class ExtensionIssue(BaseModel):
    issue_type: str
    severity: str
    affected_entity: str
    explanation: str
    current_text_evidence: Optional[str] = None
    previous_manuscript_evidence: Optional[str] = None
    source_context: Optional[str] = None
    field: Optional[str] = None
    confidence: float = 0.0
    verdict: str = "CONFIRM"


class ExtensionCheckResponse(BaseModel):
    project_id: int
    document_id: str
    document_title: Optional[str] = None
    sync_state: str
    analysis_mode: str
    has_changes: bool
    message: str
    issues: list[ExtensionIssue]
    issue_count: int
    current_hash: str
    current_revision: Optional[str] = None
    previous_synced_hash: Optional[str] = None
    previous_synced_revision: Optional[str] = None


class ExtensionSyncResponse(BaseModel):
    project_id: int
    document_id: str
    document_title: Optional[str] = None
    sync_state: str
    sync_strategy: str
    message: str
    current_hash: str
    current_revision: Optional[str] = None
    previous_synced_hash: Optional[str] = None
    synced_segment_count: int = 0
    chapters_created: list[int] = []
