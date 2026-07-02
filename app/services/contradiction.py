"""
Core contradiction detection.

Two-pass approach:
  1. LLM structured extraction — pull entities + attributes from the new chapter
  2. Attribute diffing — compare each attribute against the established entity graph
"""
from __future__ import annotations
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db import Chapter, Entity, EntityType, Alias, Contradiction, Severity
from app.models.schemas import EntityExtracted, ContradictionOut

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """\
You are a continuity analyst for long-form fiction manuscripts.
Extract ALL named entities from the chapter text.

Each entity must have:
  canonical_name: string  — the best/fullest name used in THIS chapter
  entity_type: one of CHARACTER | PLACE | PROP | EVENT | DATE
  aliases: array of all other names/references for this entity in this chapter
  attributes: known facts
    CHARACTER: eye_color, hair_color, age, status (alive|dead|unknown), occupation, relationships (object), location
    PLACE:     description, geography_notes
    PROP:      description, owner, location, status (intact|destroyed|lost|unknown)
    EVENT:     date_mention, participants, location
    DATE:      raw_text, absolute_date
  resolves_to: if this entity is the SAME as one in the known_entities list below,
               set this field to the EXACT string from that list. Otherwise omit it.

Status rules:
- CHARACTER status=dead only if explicitly confirmed dead. status=alive if they act/speak.
- PROP status=destroyed if burned/broken/lost. status=intact if physically present/used.

Only include attributes explicitly stated or strongly implied.
Return ONLY: {"entities": [{...}]}"""


def _build_extraction_prompt(chapter_text: str, known_entities: list[str]) -> str:
    prompt = chapter_text[:12000]
    if known_entities:
        known_str = json.dumps(known_entities)
        prompt = f"Known entities already in the graph: {known_str}\n\n{prompt}"
    return prompt


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.lstrip().lstrip("{").lstrip())


async def extract_entities(
    llm: AsyncOpenAI,
    chapter_text: str,
    known_entities: list[str] | None = None,
) -> list[EntityExtracted]:
    """Extract entities from chapter text, resolving against known entity names in one LLM call."""
    import asyncio
    for attempt in range(3):
        try:
            prompt = _build_extraction_prompt(chapter_text, known_entities or [])
            resp = await llm.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            data = _parse_json(raw)
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "entities" in data:
                    items = data["entities"]
                elif "items" in data:
                    items = data["items"]
                elif "canonical_name" in data:
                    items = [data]
                else:
                    items = []
            else:
                items = []
            return [EntityExtracted(**item) for item in items]
        except Exception as exc:
            if "429" in str(exc) and attempt < 2:
                wait = 15 * (attempt + 1)
                logger.warning("Rate limited, retrying in %ds (attempt %d/3)", wait, attempt + 1)
                await asyncio.sleep(wait)
            else:
                logger.warning("Entity extraction failed: %s", exc)
                return []
    return []


_JUDGE_SYSTEM = """\
You are a continuity analyst for fiction manuscripts. You receive an entity's known attributes
from previous chapters and new attributes observed in the latest chapter.

Identify ONLY genuine narrative contradictions — facts that logically cannot both be true
at the same time without an explicit in-story explanation.

=== NEVER flag these (they are not contradictions) ===
- Synonyms or rephrasing: "detective" / "investigator", "CEO" / "industrialist", "brown" / "dark"
- A character dying (alive → dead) — death is story progression
- A character being missing/disappeared — that is plot, not contradiction
- Location changes — characters move between chapters
- Age drift of 1–2 years
- A place being described with more detail ("castle" → "tall stone castle with a chapel")
- A prop's description becoming richer or more precise without logical conflict
- Any attribute where one side is "unknown", "missing", or absent

=== ALWAYS flag these ===
- Eye color change with no story reason (brown → grey)
- Hair color change with no story reason
- A dead character appearing alive again with no resurrection explained (dead → alive)
- A physically destroyed / burned / lost object reappearing intact — check the description
  carefully: if established as destroyed and now intact, that IS a contradiction regardless
  of which field it appears in
- A limb lost / gained without explanation
- An object confirmed given away then used again by the same owner

=== Severity ===
- HARD: logically impossible (dead→alive, destroyed object intact)
- SOFT: physically inconsistent but possibly explainable (hair/eye color)

Return ONLY this JSON — no prose:
{
  "contradictions": [
    {
      "field": "attribute name",
      "value_a": "what was established",
      "value_b": "what the new chapter says",
      "severity": "HARD or SOFT",
      "reason": "one sentence"
    }
  ]
}
Return {"contradictions": []} if nothing qualifies."""


async def check_and_record(
    db: AsyncSession,
    project_id: int,
    chapter_a: Chapter,
    chapter_b: Chapter,
    entity: Entity,
    incoming_attributes: dict[str, Any],
    llm: AsyncOpenAI,
) -> list[ContradictionOut]:
    """Ask the LLM to judge whether attribute changes are genuine contradictions."""
    existing = entity.attributes
    if not existing or not incoming_attributes:
        return []

    # Only pass fields that actually appear in both snapshots — reduces noise
    shared_fields = {k: v for k, v in incoming_attributes.items() if k in existing and v is not None}
    new_fields = {k: v for k, v in incoming_attributes.items() if k not in existing and v is not None}

    if not shared_fields and not new_fields:
        return []

    prompt = (
        f"Entity: {entity.canonical_name} ({entity.entity_type})\n\n"
        f"Established attributes (chapter {chapter_a.number}):\n{json.dumps(existing, indent=2)}\n\n"
        f"New attributes (chapter {chapter_b.number}):\n{json.dumps(incoming_attributes, indent=2)}"
    )

    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = json.loads(raw.lstrip().lstrip("{").lstrip())
        conflicts = data.get("contradictions", [])
    except Exception as exc:
        logger.warning("Contradiction judge failed: %s", exc)
        return []

    results: list[ContradictionOut] = []
    for conflict in conflicts:
        field = conflict.get("field", "unknown")
        val_a = str(conflict.get("value_a", ""))
        val_b = str(conflict.get("value_b", ""))
        sev_str = str(conflict.get("severity", "SOFT")).upper()
        severity = Severity.HARD if sev_str == "HARD" else Severity.SOFT

        c = Contradiction(
            project_id=project_id,
            chapter_a_id=chapter_a.id,
            chapter_b_id=chapter_b.id,
            entity_id=entity.id,
            field=field,
            value_a=val_a,
            value_b=val_b,
            severity=severity,
        )
        db.add(c)
        await db.flush()

        out = ContradictionOut.model_validate(c)
        out.chapter_a_number = chapter_a.number
        out.chapter_b_number = chapter_b.number
        results.append(out)

    return results


async def upsert_entity(
    db: AsyncSession,
    project_id: int,
    chapter: Chapter,
    extracted: EntityExtracted,
) -> tuple[Entity, bool]:
    """
    Find or create an entity. Returns (entity, is_new).
    If the LLM set resolves_to, look up by that exact canonical name (single DB hit).
    Otherwise fall back to exact match on canonical_name.
    """
    lookup_name = extracted.resolves_to or extracted.canonical_name
    result = await db.execute(
        select(Entity).where(
            Entity.project_id == project_id,
            Entity.canonical_name.ilike(lookup_name),
        )
    )
    entity = result.scalar_one_or_none()

    is_new = entity is None
    if is_new:
        entity = Entity(
            project_id=project_id,
            canonical_name=extracted.canonical_name,
            entity_type=extracted.entity_type,
            first_seen_chapter_id=chapter.id,
        )
        entity.attributes = extracted.attributes
        db.add(entity)
        await db.flush()

    # Record all name variants seen in this chapter as aliases
    for alias_text in [extracted.canonical_name] + extracted.aliases:
        existing_alias = await db.execute(
            select(Alias).where(
                Alias.entity_id == entity.id,
                Alias.chapter_id == chapter.id,
                Alias.raw_text.ilike(alias_text),
            )
        )
        if existing_alias.scalar_one_or_none() is None:
            db.add(Alias(entity_id=entity.id, chapter_id=chapter.id, raw_text=alias_text))

    return entity, is_new
