"""
GET /projects/{project_id}/graph  — entity relationship graph
GET /projects/{project_id}/timeline — chronological event timeline
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_llm
from app.models.db import Project, Entity, Alias
from app.models.schemas import GraphResponse, GraphNode, GraphEdge, TimelineResponse
from collections import defaultdict
from app.services.timeline import build_timeline

router = APIRouter(prefix="/projects/{project_id}", tags=["graph"])


@router.get("/graph", response_model=GraphResponse)
async def get_graph(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    entities_result = await db.execute(
        select(Entity).where(Entity.project_id == project_id)
    )
    entities = entities_result.scalars().all()

    nodes = [
        GraphNode(
            id=e.id,
            label=e.canonical_name,
            entity_type=e.entity_type,
            attributes=e.attributes,
        )
        for e in entities
    ]

    edges: list[GraphEdge] = []
    seen_edges: set[tuple] = set()
    name_to_id = {e.canonical_name.lower(): e.id for e in entities}

    # Edge source 1: explicit relationship attributes
    for entity in entities:
        relationships = entity.attributes.get("relationships", {})
        if isinstance(relationships, dict):
            for rel_type, related_names in relationships.items():
                if isinstance(related_names, str):
                    related_names = [related_names]
                for related_name in related_names:
                    target_id = name_to_id.get(related_name.lower())
                    if target_id and target_id != entity.id:
                        key = (min(entity.id, target_id), max(entity.id, target_id), rel_type)
                        if key not in seen_edges:
                            seen_edges.add(key)
                            edges.append(GraphEdge(source=entity.id, target=target_id, relation=rel_type))

    # Edge source 2: co-occurrence — entities that appear in the same chapter
    aliases_result = await db.execute(
        select(Alias).where(Alias.entity_id.in_([e.id for e in entities]))
    )
    aliases = aliases_result.scalars().all()

    chapter_to_entities: dict = defaultdict(set)
    for alias in aliases:
        chapter_to_entities[alias.chapter_id].add(alias.entity_id)

    for chapter_id, entity_ids in chapter_to_entities.items():
        entity_ids = list(entity_ids)
        for i in range(len(entity_ids)):
            for j in range(i + 1, len(entity_ids)):
                a, b = entity_ids[i], entity_ids[j]
                key = (min(a, b), max(a, b), "co-occurrence")
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(GraphEdge(source=a, target=b, relation="co-occurrence", weight=0.3))

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    llm=Depends(get_llm),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return await build_timeline(db, llm, project_id)
