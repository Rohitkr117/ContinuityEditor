"""
improve() logic — find high-similarity entity aliases and merge them.

"Murphy's Pub", "the pub", "the bar" → canonical: "Murphy's Pub"
"""
from __future__ import annotations
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db import Entity, Alias
from app.models.schemas import AliasGroup

logger = logging.getLogger(__name__)

_MERGE_SYSTEM = """\
You are a continuity analyst. Given a list of entity names from a fiction manuscript,
group those that clearly refer to the same entity. For each group, pick the best
canonical name (most complete / most formal).

Return JSON: {"groups": [{"canonical_name": "...", "members": ["...", "..."]}]}
Only group names you are confident refer to the same entity. Leave uncertain ones alone."""


async def find_alias_groups(
    llm: AsyncOpenAI, entity_names: list[str]
) -> list[AliasGroup]:
    """Ask LLM to cluster entity names into alias groups."""
    if not entity_names:
        return []
    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _MERGE_SYSTEM},
                {"role": "user", "content": json.dumps(entity_names)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            stripped = raw.lstrip().lstrip("{").lstrip()
            data = json.loads(stripped)
        groups = data.get("groups", [])
        return [
            AliasGroup(
                canonical_name=g["canonical_name"],
                aliases=g.get("members", []),
                confidence=0.9,
            )
            for g in groups
        ]
    except Exception as exc:
        logger.warning("Alias grouping failed: %s", exc)
        return []


async def merge_entities(
    db: AsyncSession, project_id: int, groups: list[AliasGroup]
) -> list[AliasGroup]:
    """
    For each alias group that spans multiple Entity rows, merge the duplicates
    into a single canonical Entity. Returns the groups that were actually merged.
    """
    merged: list[AliasGroup] = []

    for group in groups:
        # Find all Entity rows whose canonical_name is in this group
        rows_result = await db.execute(
            select(Entity).where(
                Entity.project_id == project_id,
                Entity.canonical_name.in_(group.aliases),
            )
        )
        entities: list[Entity] = list(rows_result.scalars().all())
        if len(entities) < 2:
            continue  # nothing to merge

        # Keep the one that matches the canonical name (or the first found)
        canonical_entity = next(
            (e for e in entities if e.canonical_name == group.canonical_name),
            entities[0],
        )
        canonical_entity.canonical_name = group.canonical_name

        # Merge attributes and re-point aliases
        for dup in entities:
            if dup.id == canonical_entity.id:
                continue
            # Merge attributes (canonical wins on conflict)
            merged_attrs = {**dup.attributes, **canonical_entity.attributes}
            canonical_entity.attributes = merged_attrs

            # Re-point all aliases to the canonical entity
            await db.execute(
                Alias.__table__.update()
                .where(Alias.entity_id == dup.id)
                .values(entity_id=canonical_entity.id)
            )
            await db.delete(dup)

        merged.append(group)

    await db.flush()
    return merged
