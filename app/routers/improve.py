"""
improve() — POST /projects/{project_id}/improve

Two-layer improvement:
  1. cognee.improve() — enriches the knowledge graph, bridges session→permanent memory
  2. Our alias canonicalization — LLM clusters near-duplicate entity names, merges them in DB
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_llm
from app.models.db import Project, Entity, Contradiction
from app.models.schemas import ImproveResponse, ContradictionOut
from app.services import cognee_service
from app.services.canonicalize import find_alias_groups, merge_entities

router = APIRouter(prefix="/projects/{project_id}/improve", tags=["improve"])


@router.post("", response_model=ImproveResponse)
async def improve(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    llm=Depends(get_llm),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Layer 1: cognee.improve() — graph enrichment + session→permanent bridge
    try:
        await cognee_service.improve(project_id)
    except Exception:
        pass  # non-fatal; our alias pass still runs

    # Layer 2: alias canonicalization via LLM clustering
    names_result = await db.execute(
        select(Entity.canonical_name).where(Entity.project_id == project_id)
    )
    names = names_result.scalars().all()

    if not names:
        return ImproveResponse(
            alias_groups_merged=[], contradictions_resolved=0, contradictions_new=[]
        )

    candidate_groups = await find_alias_groups(llm, list(names))
    merged_groups = await merge_entities(db, project_id, candidate_groups)

    new_contradictions_result = await db.execute(
        select(Contradiction).where(
            Contradiction.project_id == project_id,
            Contradiction.resolved == False,
        )
    )
    new_contradictions = new_contradictions_result.scalars().all()

    await db.commit()

    return ImproveResponse(
        alias_groups_merged=merged_groups,
        contradictions_resolved=0,
        contradictions_new=[ContradictionOut.model_validate(c) for c in new_contradictions],
    )
