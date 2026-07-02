"""
remember() — POST /projects/{project_id}/chapters

Ingestion pipeline:
  1. Persist Chapter row
  2. cognee.remember() — store chapter as permanent graph memory (background)
  3. LLM structured entity extraction (synchronous — needed for immediate contradiction check)
  4. Upsert entities; diff attributes against existing graph
  5. Persist contradictions; return full report
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db, get_llm
from app.models.db import Project, Chapter, Entity
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

    all_contradictions = []
    for extracted in extracted_entities:
        entity, is_new = await cs.upsert_entity(db, project_id, chapter, extracted)

        if not is_new and extracted.attributes:
            first_chapter = await db.get(Chapter, entity.first_seen_chapter_id)
            if first_chapter:
                new_contradictions = await cs.check_and_record(
                    db, project_id, first_chapter, chapter, entity, extracted.attributes, llm
                )
                all_contradictions.extend(new_contradictions)

            # Merge attributes: existing wins on most fields (established facts),
            # but status is always updated to the latest chapter's value so that
            # a character dying or a prop being destroyed propagates forward.
            merged = {**extracted.attributes, **entity.attributes}
            if "status" in extracted.attributes and extracted.attributes["status"] not in (None, "unknown"):
                merged["status"] = extracted.attributes["status"]
            entity.attributes = merged

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
