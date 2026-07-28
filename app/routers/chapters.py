"""
remember() — POST /projects/{project_id}/chapters

Ingestion pipeline:
  1. Persist Chapter row
  2. cognee.remember() — store chapter as permanent graph memory (background)
  3. LLM structured entity extraction (synchronous — needed for immediate contradiction check)
  4. Upsert entities; diff attributes against existing graph
  5. Persist contradictions; return full report
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db, get_llm
from app.models.db import Project, Chapter, Entity, Alias
from app.models.schemas import ChapterIngest, ChapterIngestResponse, ChapterOut
from app.services import cognee_service
from app.services import contradiction as cs

router = APIRouter(prefix="/projects/{project_id}/chapters", tags=["chapters"])


@router.post("", response_model=ChapterIngestResponse, status_code=201)
async def ingest_chapter(
    project_id: int,
    body: ChapterIngest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    llm=Depends(get_llm),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    existing = await db.execute(
        select(Chapter).where(
            Chapter.project_id == project_id,
            Chapter.number == body.number,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Chapter {body.number} already exists for this project")

    chapter = Chapter(
        project_id=project_id,
        number=body.number,
        title=body.title,
        raw_text=body.text,
    )
    db.add(chapter)
    await db.flush()

    # cognee.remember() stores this chapter into the project's knowledge graph.
    # Run in background — graph construction is slow for large chapters.
    background_tasks.add_task(
        cognee_service.remember, project_id, body.number, body.text
    )

    # Fetch existing entity names so the LLM can resolve aliases in one pass
    existing_result = await db.execute(
        select(Entity.canonical_name).where(Entity.project_id == project_id)
    )
    known_entities = existing_result.scalars().all()

    # LLM structured extraction — passes known entity names so the model can set
    # resolves_to and collapse "Cole" → "Marcus Cole" without multi-pass DB lookups.
    extracted_entities = await cs.extract_entities(llm, body.text, list(known_entities))

    # Per-entity proposer agents are collected here and run concurrently below, then
    # reviewed together by a single final arbiter call for this chapter ingest.
    # existing_attrs is snapshotted BEFORE the merge below overwrites entity.attributes,
    # since the proposer calls are deferred until after this whole loop finishes.
    check_jobs: list[tuple[Entity, list[Chapter], dict, dict]] = []

    for extracted in extracted_entities:
        entity, is_new = await cs.upsert_entity(db, project_id, chapter, extracted)

        if not is_new and extracted.attributes:
            existing_attrs = dict(entity.attributes)

            # Fetch all previous chapters in this project where this entity appeared (has aliases)
            prev_chapters_result = await db.execute(
                select(Chapter)
                .join(Alias)
                .where(
                    Alias.entity_id == entity.id,
                    Chapter.project_id == project_id,
                    Chapter.number < chapter.number
                )
                .order_by(Chapter.number.asc())
            )
            # Use a dict to keep chapters unique by ID (ordered by number)
            prev_chapters_map = {c.id: c for c in prev_chapters_result.scalars().all()}
            previous_chapters = list(prev_chapters_map.values())

            if not previous_chapters:
                first_chapter = await db.get(Chapter, entity.first_seen_chapter_id)
                previous_chapters = [first_chapter] if first_chapter else []

            if previous_chapters:
                check_jobs.append((entity, previous_chapters, existing_attrs, extracted.attributes))

            # Merge attributes: new attributes win and propagate forward,
            # but we deep-merge nested 'relationships' so that other relationships are not lost.
            merged = {**entity.attributes, **extracted.attributes}

            if "relationships" in entity.attributes and "relationships" in extracted.attributes:
                existing_rels = entity.attributes["relationships"] or {}
                extracted_rels = extracted.attributes["relationships"] or {}
                if isinstance(existing_rels, dict) and isinstance(extracted_rels, dict):
                    merged["relationships"] = {**existing_rels, **extracted_rels}

            entity.attributes = merged

    all_contradictions = []
    if check_jobs:
        # Multi-agent proposer stage: one analyst call per entity, run in parallel.
        proposals = await asyncio.gather(*[
            cs.propose_for_entity(prev_chapters, chapter, entity, existing_attrs, attrs, llm)
            for entity, prev_chapters, existing_attrs, attrs in check_jobs
        ])
        candidates = [candidate for group in proposals for candidate in group]

        # Final judge stage: one batched call reviews every candidate from this ingest.
        all_contradictions = await cs.arbitrate_and_persist(db, project_id, candidates, llm)

    await db.commit()

    return ChapterIngestResponse(
        chapter_id=chapter.id,
        chapter_number=chapter.number,
        entities_extracted=extracted_entities,
        contradictions_found=all_contradictions,
    )


@router.get("", response_model=list[ChapterOut])
async def list_chapters(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.number)
    )
    return result.scalars().all()
