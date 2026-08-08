from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

from app.models.db import Alias, Chapter, DocumentSyncState, Entity, Project
from app.models.schemas import (
    ExtensionCheckResponse,
    ExtensionDocumentRequest,
    ExtensionIssue,
    ExtensionStatusResponse,
    ExtensionSyncResponse,
)
from app.services import cognee_service
from app.services import contradiction as cs


@dataclass
class DeltaResult:
    mode: str
    text: str
    has_changes: bool
    message: str


def normalize_document_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def compute_document_hash(text: str) -> str:
    normalized = normalize_document_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _merge_ranges(ranges: list[tuple[int, int]], gap: int = 80) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def derive_document_delta(previous_text: str | None, current_text: str) -> DeltaResult:
    previous = normalize_document_text(previous_text or "")
    current = normalize_document_text(current_text)

    if not current:
        return DeltaResult("empty", "", False, "The Google Doc is empty.")
    if not previous:
        return DeltaResult("full", current, True, "No previous sync found; using the current document content.")
    if current == previous:
        return DeltaResult("unchanged", "", False, "This document is already synced.")
    if current.startswith(previous):
        appended = current[len(previous):].strip()
        if not appended:
            return DeltaResult("unchanged", "", False, "This document is already synced.")
        return DeltaResult("append", appended, True, "Using newly appended document text.")

    matcher = SequenceMatcher(None, previous, current, autojunk=False)
    changed_ranges: list[tuple[int, int]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"insert", "replace"} and j1 != j2:
            changed_ranges.append((max(0, j1 - 120), min(len(current), j2 + 120)))

    merged_ranges = _merge_ranges(changed_ranges)
    snippets = []
    for index, (start, end) in enumerate(merged_ranges, start=1):
        snippet = current[start:end].strip()
        if snippet:
            snippets.append(f"[Edited passage {index}]\n{snippet}")

    if not snippets:
        return DeltaResult(
            "unchanged",
            "",
            False,
            "No meaningful text changes were detected since the last sync.",
        )

    return DeltaResult(
        "edited_passages",
        "\n\n".join(snippets),
        True,
        "Using edited passages because earlier synced text was modified.",
    )


async def get_or_create_sync_state(
    db: AsyncSession,
    project_id: int,
    document_id: str,
    document_title: str | None = None,
) -> DocumentSyncState:
    result = await db.execute(
        select(DocumentSyncState).where(
            DocumentSyncState.project_id == project_id,
            DocumentSyncState.document_id == document_id,
        )
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = DocumentSyncState(
            project_id=project_id,
            document_id=document_id,
            document_title=document_title,
        )
        db.add(state)
        await db.flush()
    elif document_title:
        state.document_title = document_title
    return state


async def build_status_response(
    db: AsyncSession,
    project: Project,
    document_id: str,
    document_title: str | None = None,
    current_hash: str | None = None,
    current_revision: str | None = None,
) -> ExtensionStatusResponse:
    state = await get_or_create_sync_state(db, project.id, document_id, document_title)

    if not state.last_synced_hash:
        sync_state = "NOT_SYNCED"
    elif current_hash and current_hash == state.last_synced_hash:
        sync_state = "SYNCED"
    elif current_revision and state.last_synced_revision and current_revision == state.last_synced_revision:
        sync_state = "SYNCED"
    else:
        sync_state = "OUT_OF_SYNC"

    return ExtensionStatusResponse(
        project_id=project.id,
        project_title=project.title,
        document_id=document_id,
        document_title=state.document_title or document_title,
        sync_state=sync_state,
        has_synced_content=bool(state.last_synced_hash),
        last_synced_hash=state.last_synced_hash,
        last_synced_revision=state.last_synced_revision,
        last_synced_at=state.updated_at if state.last_synced_hash else None,
        last_checked_hash=state.last_checked_hash,
        last_checked_revision=state.last_checked_revision,
        last_issue_count=state.last_issue_count,
        synced_segment_count=state.synced_segment_count,
    )


async def _fetch_known_entities(db: AsyncSession, project_id: int) -> list[str]:
    result = await db.execute(select(Entity.canonical_name).where(Entity.project_id == project_id))
    return list(result.scalars().all())


async def _fetch_previous_chapters(
    db: AsyncSession,
    project_id: int,
    entity_id: int,
    chapter_number: int,
) -> list[Chapter]:
    result = await db.execute(
        select(Chapter)
        .join(Alias)
        .where(
            Alias.entity_id == entity_id,
            Chapter.project_id == project_id,
            Chapter.number < chapter_number,
        )
        .order_by(Chapter.number.asc())
    )
    chapter_map = {chapter.id: chapter for chapter in result.scalars().all()}
    previous_chapters = list(chapter_map.values())
    if previous_chapters:
        return previous_chapters

    entity = await db.get(Entity, entity_id)
    if entity and entity.first_seen_chapter_id:
        first_chapter = await db.get(Chapter, entity.first_seen_chapter_id)
        if first_chapter:
            return [first_chapter]
    return []


async def _next_chapter_number(db: AsyncSession, project_id: int) -> int:
    result = await db.execute(select(func.max(Chapter.number)).where(Chapter.project_id == project_id))
    max_number = result.scalar_one_or_none() or 0
    return int(max_number) + 1


def _build_issue_type(field: str, value_a: str, value_b: str) -> str:
    lowered = field.lower()
    combined = f"{value_a} {value_b}".lower()
    if lowered == "status" and "dead" in combined and "alive" in combined:
        return "Dead Man Walking"
    if lowered in {"eye_color", "hair_color", "age", "occupation"}:
        return "Character Attribute Conflict"
    if lowered in {"date_mention", "absolute_date"}:
        return "Timeline Conflict"
    if lowered == "location":
        return "Location Continuity Conflict"
    if lowered == "owner":
        return "Prop Continuity Conflict"
    if lowered == "relationships":
        return "Relationship Continuity Conflict"
    return "Continuity Conflict"


def build_extension_issue(item: dict) -> ExtensionIssue:
    chapter_label = item.get("chapter_a_number")
    source_context = f"Chapter {chapter_label}" if chapter_label is not None else None
    previous_evidence = item.get("quote_a") or item.get("value_a")
    current_evidence = item.get("quote_b") or item.get("value_b")
    return ExtensionIssue(
        issue_type=_build_issue_type(item["field"], item["value_a"], item["value_b"]),
        severity=item["severity"].value,
        affected_entity=item.get("entity_name") or "Unknown entity",
        explanation=item.get("reason") or f"{item['field']} changed from {item['value_a']} to {item['value_b']}.",
        current_text_evidence=current_evidence,
        previous_manuscript_evidence=previous_evidence,
        source_context=source_context,
        field=item["field"],
        confidence=item.get("confidence", 0.0),
        verdict=item.get("verdict", "CONFIRM"),
    )


async def analyze_document_check(
    db: AsyncSession,
    project: Project,
    request: ExtensionDocumentRequest,
    llm: AsyncOpenAI,
) -> ExtensionCheckResponse:
    normalized_text = normalize_document_text(request.document_text)
    current_hash = compute_document_hash(normalized_text)
    state = await get_or_create_sync_state(db, project.id, request.document_id, request.document_title)
    previous_synced_hash = state.last_synced_hash
    previous_synced_revision = state.last_synced_revision
    delta = derive_document_delta(state.last_synced_text, normalized_text)

    state.last_checked_hash = current_hash
    state.last_checked_revision = request.document_revision
    if request.document_title:
        state.document_title = request.document_title

    if not delta.has_changes:
        state.last_issue_count = 0
        sync_state = "SYNCED" if previous_synced_hash and previous_synced_hash == current_hash else "NOT_SYNCED"
        return ExtensionCheckResponse(
            project_id=project.id,
            document_id=request.document_id,
            document_title=state.document_title,
            sync_state=sync_state,
            analysis_mode=delta.mode,
            has_changes=False,
            message=delta.message,
            issues=[],
            issue_count=0,
            current_hash=current_hash,
            current_revision=request.document_revision,
            previous_synced_hash=previous_synced_hash,
            previous_synced_revision=previous_synced_revision,
        )

    known_entities = await _fetch_known_entities(db, project.id)
    extracted_entities = await cs.extract_entities(llm, delta.text, known_entities)
    preview_number = await _next_chapter_number(db, project.id)
    preview_chapter = Chapter(
        project_id=project.id,
        number=preview_number,
        title=request.document_title,
        raw_text=delta.text,
    )

    check_jobs: list[tuple[Entity, list[Chapter], dict, dict]] = []
    for extracted in extracted_entities:
        entity = await cs.resolve_entity(db, project.id, extracted)
        if entity is None or not extracted.attributes:
            continue
        existing_attributes = dict(entity.attributes)
        previous_chapters = await _fetch_previous_chapters(db, project.id, entity.id, preview_number)
        if previous_chapters:
            check_jobs.append((entity, previous_chapters, existing_attributes, extracted.attributes))

    candidates: list[dict] = []
    if check_jobs:
        proposals = await asyncio.gather(*[
            cs.propose_for_entity(previous_chapters, preview_chapter, entity, existing_attributes, incoming_attributes, llm)
            for entity, previous_chapters, existing_attributes, incoming_attributes in check_jobs
        ])
        for group in proposals:
            candidates.extend(group)

    judged = await cs.arbitrate_candidates(candidates, llm)
    confirmed = [item for item in judged if item["verdict"] == "CONFIRM"]
    issues = [build_extension_issue(item) for item in confirmed]
    state.last_issue_count = len(issues)

    sync_state = "SYNCED" if previous_synced_hash and previous_synced_hash == current_hash else "OUT_OF_SYNC"
    message = "No continuity issues found." if not issues else f"Found {len(issues)} continuity issue(s)."

    return ExtensionCheckResponse(
        project_id=project.id,
        document_id=request.document_id,
        document_title=state.document_title,
        sync_state=sync_state,
        analysis_mode=delta.mode,
        has_changes=True,
        message=message,
        issues=issues,
        issue_count=len(issues),
        current_hash=current_hash,
        current_revision=request.document_revision,
        previous_synced_hash=previous_synced_hash,
        previous_synced_revision=previous_synced_revision,
    )


async def _ingest_sync_segment(
    db: AsyncSession,
    project: Project,
    document_id: str,
    document_title: str | None,
    segment_text: str,
    content_hash: str,
    llm: AsyncOpenAI,
    background_tasks: Optional[BackgroundTasks] = None,
) -> int:
    chapter_number = await _next_chapter_number(db, project.id)
    chapter = Chapter(
        project_id=project.id,
        number=chapter_number,
        title=document_title or f"Google Docs Sync {chapter_number}",
        raw_text=segment_text,
        source_type="GOOGLE_DOCS_SYNC",
        external_document_id=document_id,
        content_hash=content_hash,
    )
    db.add(chapter)
    await db.flush()

    if background_tasks is not None:
        background_tasks.add_task(cognee_service.remember, project.id, chapter.number, segment_text)
    else:
        await cognee_service.remember(project.id, chapter.number, segment_text)

    known_entities = await _fetch_known_entities(db, project.id)
    extracted_entities = await cs.extract_entities(llm, segment_text, known_entities)
    check_jobs: list[tuple[Entity, list[Chapter], dict, dict]] = []

    for extracted in extracted_entities:
        entity, is_new = await cs.upsert_entity(db, project.id, chapter, extracted)
        if not is_new and extracted.attributes:
            existing_attributes = dict(entity.attributes)
            previous_chapters = await _fetch_previous_chapters(db, project.id, entity.id, chapter.number)
            if previous_chapters:
                check_jobs.append((entity, previous_chapters, existing_attributes, extracted.attributes))

            merged = {**entity.attributes, **extracted.attributes}
            if "relationships" in entity.attributes and "relationships" in extracted.attributes:
                existing_relationships = entity.attributes["relationships"] or {}
                extracted_relationships = extracted.attributes["relationships"] or {}
                if isinstance(existing_relationships, dict) and isinstance(extracted_relationships, dict):
                    merged["relationships"] = {**existing_relationships, **extracted_relationships}
            entity.attributes = merged

    if check_jobs:
        proposals = await asyncio.gather(*[
            cs.propose_for_entity(previous_chapters, chapter, entity, existing_attributes, incoming_attributes, llm)
            for entity, previous_chapters, existing_attributes, incoming_attributes in check_jobs
        ])
        candidates = [candidate for group in proposals for candidate in group]
        await cs.arbitrate_and_persist(db, project.id, candidates, llm)

    return chapter.id


async def sync_document_to_project(
    db: AsyncSession,
    project: Project,
    request: ExtensionDocumentRequest,
    llm: AsyncOpenAI,
    background_tasks: Optional[BackgroundTasks] = None,
) -> ExtensionSyncResponse:
    normalized_text = normalize_document_text(request.document_text)
    current_hash = compute_document_hash(normalized_text)
    state = await get_or_create_sync_state(db, project.id, request.document_id, request.document_title)
    previous_synced_hash = state.last_synced_hash
    delta = derive_document_delta(state.last_synced_text, normalized_text)

    if request.document_title:
        state.document_title = request.document_title

    if not delta.has_changes:
        return ExtensionSyncResponse(
            project_id=project.id,
            document_id=request.document_id,
            document_title=state.document_title,
            sync_state="SYNCED" if state.last_synced_hash else "NOT_SYNCED",
            sync_strategy=delta.mode,
            message=delta.message,
            current_hash=current_hash,
            current_revision=request.document_revision,
            previous_synced_hash=previous_synced_hash,
            synced_segment_count=state.synced_segment_count,
            chapters_created=[],
        )

    chapter_id = await _ingest_sync_segment(
        db=db,
        project=project,
        document_id=request.document_id,
        document_title=request.document_title,
        segment_text=delta.text,
        content_hash=current_hash,
        llm=llm,
        background_tasks=background_tasks,
    )

    state.last_synced_hash = current_hash
    state.last_synced_revision = request.document_revision
    state.last_synced_text = normalized_text
    state.last_checked_hash = current_hash
    state.last_checked_revision = request.document_revision
    state.last_sync_strategy = delta.mode
    state.synced_segment_count += 1

    return ExtensionSyncResponse(
        project_id=project.id,
        document_id=request.document_id,
        document_title=state.document_title,
        sync_state="SYNCED",
        sync_strategy=delta.mode,
        message=delta.message,
        current_hash=current_hash,
        current_revision=request.document_revision,
        previous_synced_hash=previous_synced_hash,
        synced_segment_count=state.synced_segment_count,
        chapters_created=[chapter_id],
    )
