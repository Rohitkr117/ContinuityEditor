"""
recall() — POST /projects/{project_id}/recall

Two-layer recall:
  1. cognee.recall() — semantic search across the project's knowledge graph
  2. DB contradiction records — structured conflicts detected at ingest time

Both results are returned so the caller gets the full picture.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.db import Project, Entity, Contradiction, Chapter
from app.models.schemas import RecallRequest, RecallResponse, ContradictionOut, CogneeHit
from app.services import cognee_service

router = APIRouter(prefix="/projects/{project_id}/recall", tags=["recall"])


@router.post("", response_model=RecallResponse)
async def recall(
    project_id: int,
    body: RecallRequest,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Layer 1: cognee.recall() — semantic graph search for the focus entity/topic
    # Results are Pydantic objects: use result.text / result.source, NOT result["text"]
    cognee_hits = []
    if body.focus:
        try:
            raw_hits = await cognee_service.recall(project_id, body.focus)
            cognee_hits = [
                CogneeHit(
                    text=getattr(hit, "text", None),
                    source=getattr(hit, "source", None),
                    score=getattr(hit, "score", None),
                )
                for hit in raw_hits
            ]
        except Exception:
            pass  # graph may not be built yet for brand-new projects

    # Layer 2: DB contradiction records
    stmt = select(Contradiction).where(
        Contradiction.project_id == project_id,
        Contradiction.resolved == False,
    )

    if body.focus:
        entity_ids_result = await db.execute(
            select(Entity.id).where(
                Entity.project_id == project_id,
                Entity.canonical_name.ilike(f"%{body.focus}%"),
            )
        )
        entity_ids = entity_ids_result.scalars().all()
        stmt = stmt.where(Contradiction.entity_id.in_(entity_ids))

    if body.chapter_ids:
        stmt = stmt.where(
            (Contradiction.chapter_a_id.in_(body.chapter_ids)) |
            (Contradiction.chapter_b_id.in_(body.chapter_ids))
        )

    result = await db.execute(stmt.order_by(Contradiction.created_at.desc()))
    contradictions = result.scalars().all()

    # Scope metadata
    chapters_result = await db.execute(
        select(Chapter).where(Chapter.project_id == project_id)
    )
    chapters = chapters_result.scalars().all()
    ch_num = {c.id: c.number for c in chapters}

    entities_result = await db.execute(
        select(Entity).where(Entity.project_id == project_id)
    )
    entities = entities_result.scalars().all()

    def enrich(c: Contradiction) -> ContradictionOut:
        out = ContradictionOut.model_validate(c)
        out.chapter_a_number = ch_num.get(c.chapter_a_id)
        out.chapter_b_number = ch_num.get(c.chapter_b_id)
        return out

    return RecallResponse(
        contradictions=[enrich(c) for c in contradictions],
        cognee_hits=cognee_hits,
        checked_chapters=len(body.chapter_ids or [c.id for c in chapters]),
        checked_entities=len(entities),
    )


@router.patch("/{contradiction_id}/resolve", status_code=200)
async def resolve_contradiction(
    project_id: int,
    contradiction_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Mark a contradiction as intentional / resolved by the author."""
    c = await db.get(Contradiction, contradiction_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "Contradiction not found")
    c.resolved = True
    await db.commit()
    return {"id": contradiction_id, "resolved": True}
