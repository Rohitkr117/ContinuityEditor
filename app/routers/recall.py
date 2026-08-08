from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.db import Chapter, Contradiction, Entity, Project
from app.models.schemas import CogneeHit, ContradictionOut, RecallRequest, RecallResponse
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
            pass

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
            (Contradiction.chapter_a_id.in_(body.chapter_ids))
            | (Contradiction.chapter_b_id.in_(body.chapter_ids))
        )

    result = await db.execute(stmt.order_by(Contradiction.created_at.desc()))
    contradictions = result.scalars().all()

    chapters_result = await db.execute(select(Chapter).where(Chapter.project_id == project_id))
    chapters = chapters_result.scalars().all()
    chapter_numbers = {chapter.id: chapter.number for chapter in chapters}

    entities_result = await db.execute(select(Entity).where(Entity.project_id == project_id))
    entities = entities_result.scalars().all()
    entity_names = {entity.id: entity.canonical_name for entity in entities}

    def enrich(contradiction: Contradiction) -> ContradictionOut:
        out = ContradictionOut.model_validate(contradiction)
        out.chapter_a_number = chapter_numbers.get(contradiction.chapter_a_id)
        out.chapter_b_number = chapter_numbers.get(contradiction.chapter_b_id)
        out.entity_name = entity_names.get(contradiction.entity_id)
        return out

    return RecallResponse(
        contradictions=[enrich(item) for item in contradictions],
        cognee_hits=cognee_hits,
        checked_chapters=len(body.chapter_ids or [chapter.id for chapter in chapters]),
        checked_entities=len(entities),
    )


@router.patch("/{contradiction_id}/resolve", status_code=200)
async def resolve_contradiction(
    project_id: int,
    contradiction_id: int,
    db: AsyncSession = Depends(get_db),
):
    contradiction = await db.get(Contradiction, contradiction_id)
    if not contradiction or contradiction.project_id != project_id:
        raise HTTPException(404, "Contradiction not found")
    contradiction.resolved = True
    await db.commit()
    return {"id": contradiction_id, "resolved": True}
