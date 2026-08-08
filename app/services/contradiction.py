from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db import Alias, Chapter, Contradiction, Entity, EntityType, Severity
from app.models.schemas import ContradictionOut, EntityExtracted

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """\
You are a continuity analyst for long-form fiction manuscripts.
Extract ALL named entities from the chapter text.

Each entity must have:
  canonical_name: string - the best/fullest name used in THIS chapter
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
    candidates = [raw, raw.lstrip().lstrip("{").lstrip()]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            obj, _ = decoder.raw_decode(candidate)
            return obj
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("Unparseable model response", raw, 0)


async def extract_entities(
    llm: AsyncOpenAI,
    chapter_text: str,
    known_entities: list[str] | None = None,
) -> list[EntityExtracted]:
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


_PROPOSER_SYSTEM = """\
You are a continuity analyst for fiction manuscripts. You receive one entity's known
attributes from previous chapters and the changed/new attributes observed in the latest
chapter, plus the raw text of both so you can find exact evidence quotes.

A genuine contradiction is a pair of facts about the SAME entity that cannot both be true
at the same time, with no plausible in-story explanation available in the text (e.g.
death, disguise, injury/healing, deliberate change, the passage of time). Judge each
attribute change on its underlying meaning, not surface wording - rephrasing, added
detail, or ambiguous wording alone are not contradictions.

You are the first stage of a two-stage pipeline: a separate judge will review every
candidate you raise before anything is shown to the writer, using only what you report
here. Raise anything plausible, but you MUST self-assess how confident you are that it
is a genuine, narratively-unexplained contradiction:
  0.8-1.0 = both values are explicit and directly conflict; no plausible explanation in the text
  0.5-0.79 = values plausibly conflict but wording, context, or partial evidence leaves room for doubt
  0.0-0.49 = weak or speculative - do not include these at all

=== Severity (your best assessment; the downstream judge makes the final call) ===
- HARD: the two states are mutually exclusive with no plausible explanation (e.g.
  simultaneously alive and confirmed dead, or a destroyed object appearing intact)
- SOFT: inconsistent but plausibly explainable by ordinary narrative drift (e.g. a
  sensory/descriptive detail differing slightly)

=== Evidence quotes ===
For each candidate, find the shortest exact sentence or phrase from each chapter's raw
text that best supports the flagged value. Use null if you cannot find a clear quote -
never invent a quote that doesn't appear in the text; a fabricated quote will be caught
and discarded automatically, so there is nothing to gain by guessing one.

Return ONLY this JSON - no prose:
{
  "contradictions": [
    {
      "field": "attribute name",
      "value_a": "what was established",
      "value_b": "what the new chapter says",
      "severity": "HARD or SOFT",
      "confidence": 0.0,
      "reason": "one sentence explaining the conflict and why it isn't explainable",
      "quote_a": "exact short quote from chapter A text, or null",
      "quote_b": "exact short quote from chapter B text, or null"
    }
  ]
}
Return {"contradictions": []} if nothing qualifies."""

_MULTI_CHAPTER_SUFFIX = (
    "\n\n=== IMPORTANT FORMATTING RULE ===\n"
    "Since multiple previous chapters are provided, you MUST identify which specific "
    "previous chapter the established value ('value_a') was actually mentioned in.\n"
    "Include the 'chapter_a_number' field (integer) in each candidate, and extract "
    "'quote_a' from that specific chapter's raw text.\n"
    "Required JSON output structure:\n"
    "{\n"
    "  \"contradictions\": [\n"
    "    {\n"
    "      \"field\": \"attribute name\",\n"
    "      \"value_a\": \"established value\",\n"
    "      \"value_b\": \"new chapter value\",\n"
    "      \"severity\": \"HARD or SOFT\",\n"
    "      \"confidence\": 0.0,\n"
    "      \"reason\": \"one sentence explaining the conflict\",\n"
    "      \"chapter_a_number\": 2,\n"
    "      \"quote_a\": \"exact quote from chapter 2, or null\",\n"
    "      \"quote_b\": \"exact quote from chapter B, or null\"\n"
    "    }\n"
    "  ]\n"
    "}"
)

_NULL_LIKE = frozenset({
    "none", "null", "unknown", "n/a", "na", "not mentioned",
    "not specified", "not stated", "unspecified", "",
})

_SYNONYM_VALUES = {
    "grey": "gray",
}


def _is_null_like(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULL_LIKE:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _strip_null_like(attrs: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in attrs.items():
        if isinstance(value, dict):
            inner = {inner_key: inner_value for inner_key, inner_value in value.items() if not _is_null_like(inner_value)}
            if inner:
                cleaned[key] = inner
        elif not _is_null_like(value):
            cleaned[key] = value
    return cleaned


def _normalize_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)
    normalized = re.sub(r"\s+", " ", str(value).strip().lower())
    return _SYNONYM_VALUES.get(normalized, normalized)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _quote_is_grounded(quote: str | None, source_text: str, threshold: float = 0.85) -> bool:
    if not quote:
        return False
    normalized_quote = _normalize_text(quote)
    if len(normalized_quote) < 3:
        return False
    normalized_source = _normalize_text(source_text)
    if normalized_quote in normalized_source:
        return True
    matcher = difflib.SequenceMatcher(None, normalized_quote, normalized_source)
    match = matcher.find_longest_match(0, len(normalized_quote), 0, len(normalized_source))
    return (match.size / len(normalized_quote)) >= threshold


async def propose_for_entity(
    previous_chapters: list[Chapter],
    chapter_b: Chapter,
    entity: Entity,
    existing_attributes: dict[str, Any],
    incoming_attributes: dict[str, Any],
    llm: AsyncOpenAI,
) -> list[dict[str, Any]]:
    existing = existing_attributes
    if not existing or not incoming_attributes:
        return []

    cleaned_incoming = _strip_null_like(incoming_attributes)
    if not cleaned_incoming:
        return []

    changed_or_new = {
        key: value
        for key, value in cleaned_incoming.items()
        if key not in existing or _normalize_value(existing[key]) != _normalize_value(value)
    }
    if not changed_or_new:
        return []

    texts_a = []
    for chapter in previous_chapters:
        texts_a.append(f"--- Chapter {chapter.number} raw text (truncated) ---\n{(chapter.raw_text or '')[:4000]}")
    joined_texts_a = "\n\n".join(texts_a)

    prompt = (
        f"Entity: {entity.canonical_name} ({entity.entity_type})\n\n"
        f"Established attributes (across previous chapters):\n"
        f"{json.dumps(existing, indent=2)}\n\n"
        f"Changed/new attributes (chapter {chapter_b.number}):\n"
        f"{json.dumps(changed_or_new, indent=2)}\n\n"
        f"=== PREVIOUS CHAPTERS ===\n{joined_texts_a}\n\n"
        f"=== NEW CHAPTER ===\n--- Chapter {chapter_b.number} raw text ---\n{(chapter_b.raw_text or '')[:4000]}"
        f"{_MULTI_CHAPTER_SUFFIX}"
    )

    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _PROPOSER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_json(raw)
        raw_candidates = data.get("contradictions", [])
    except Exception as exc:
        logger.warning("Proposer failed for entity %s: %s", entity.canonical_name, exc)
        return []

    candidates: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        chapter_a_num = candidate.get("chapter_a_number")
        chapter_a = None
        if chapter_a_num is not None:
            try:
                chapter_a = next((item for item in previous_chapters if item.number == int(chapter_a_num)), None)
            except (ValueError, TypeError):
                pass
        if not chapter_a:
            chapter_a = previous_chapters[0]

        quote_a = candidate.get("quote_a") or None
        quote_b = candidate.get("quote_b") or None
        quote_a_grounded = _quote_is_grounded(quote_a, chapter_a.raw_text or "")
        quote_b_grounded = _quote_is_grounded(quote_b, chapter_b.raw_text or "")
        if quote_a and not quote_a_grounded:
            logger.warning(
                "Proposer produced an ungrounded quote_a for %s/%s: %r",
                entity.canonical_name,
                candidate.get("field"),
                quote_a,
            )
            quote_a = None
        if quote_b and not quote_b_grounded:
            logger.warning(
                "Proposer produced an ungrounded quote_b for %s/%s: %r",
                entity.canonical_name,
                candidate.get("field"),
                quote_b,
            )
            quote_b = None

        try:
            confidence = float(candidate.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        severity_str = str(candidate.get("severity", "SOFT")).upper()
        proposer_severity = Severity.HARD if severity_str == "HARD" else Severity.SOFT

        candidates.append({
            "entity_id": entity.id,
            "entity_name": entity.canonical_name,
            "field": candidate.get("field", "unknown"),
            "value_a": str(candidate.get("value_a", "")),
            "value_b": str(candidate.get("value_b", "")),
            "proposer_severity": proposer_severity,
            "proposer_confidence": confidence,
            "proposer_reason": candidate.get("reason") or None,
            "quote_a": quote_a,
            "quote_b": quote_b,
            "quote_a_grounded": quote_a_grounded,
            "quote_b_grounded": quote_b_grounded,
            "chapter_a_id": chapter_a.id,
            "chapter_a_number": chapter_a.number,
            "chapter_b_id": chapter_b.id,
            "chapter_b_number": chapter_b.number,
        })

    return candidates


_ARBITER_SYSTEM = """\
You are the final arbiter in a continuity-detection pipeline for fiction manuscripts.
Several per-entity analyst agents have each proposed candidate contradictions. You do
NOT have access to the original chapter text - you must judge each candidate using only
the structured evidence given: the field, the two conflicting values, the proposer's
severity/confidence/reason, the evidence quotes (if any), and whether each quote was
independently verified as appearing in the source chapter.

For each candidate, decide:
  - verdict: "CONFIRM" if this is a genuine, narratively-unexplained contradiction worth
    surfacing to the writer; "REJECT" if the two values are plausibly compatible, too
    weakly evidenced, or too ambiguous to assert as a contradiction.
  - confidence: your own 0.0-1.0 confidence in this verdict. Weigh quote verification
    heavily - an unverified or missing quote on either side should pull confidence down,
    since there is no independently-checked evidence backing the claim.
  - severity: "HARD" or "SOFT" - your own assessment (you may agree or disagree with the
    proposer). Fill it in even when rejecting, as your best guess.
  - reason: one sentence justifying the verdict.

Be skeptical by default - the proposer stage is allowed to over-generate; your job is to
filter it down. When in doubt between CONFIRM and REJECT, prefer REJECT with a mid-range
confidence rather than CONFIRM with low confidence.

Input is a JSON array of candidates, each with an "id". Return ONLY this JSON - no prose:
{
  "verdicts": [
    {"id": 0, "verdict": "CONFIRM or REJECT", "confidence": 0.0, "severity": "HARD or SOFT", "reason": "..."}
  ]
}
Return exactly one verdict per candidate id."""


async def arbitrate_candidates(
    candidates: list[dict[str, Any]],
    llm: AsyncOpenAI,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    payload = [
        {
            "id": index,
            "entity": candidate["entity_name"],
            "field": candidate["field"],
            "value_a": candidate["value_a"],
            "value_b": candidate["value_b"],
            "proposer_severity": candidate["proposer_severity"].value,
            "proposer_confidence": candidate["proposer_confidence"],
            "proposer_reason": candidate["proposer_reason"],
            "quote_a": candidate["quote_a"],
            "quote_b": candidate["quote_b"],
            "quote_a_verified": candidate["quote_a_grounded"],
            "quote_b_verified": candidate["quote_b_grounded"],
        }
        for index, candidate in enumerate(candidates)
    ]

    verdicts: dict[int, dict[str, Any]] = {}
    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _ARBITER_SYSTEM},
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_json(raw)
        for verdict in data.get("verdicts", []):
            try:
                idx = int(verdict.get("id"))
            except (TypeError, ValueError):
                continue
            verdicts[idx] = verdict
    except Exception as exc:
        logger.warning("Arbiter call failed, rejecting all %d candidate(s): %s", len(candidates), exc)

    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        verdict = verdicts.get(index)
        if verdict is None:
            verdict_str = "REJECT"
            confidence = 0.0
            severity = candidate["proposer_severity"]
            reason = candidate["proposer_reason"] or "no arbiter verdict returned"
        else:
            verdict_str = "CONFIRM" if str(verdict.get("verdict", "REJECT")).upper() == "CONFIRM" else "REJECT"
            try:
                confidence = max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            severity_str = str(verdict.get("severity", candidate["proposer_severity"].value)).upper()
            severity = Severity.HARD if severity_str == "HARD" else Severity.SOFT
            reason = verdict.get("reason") or candidate["proposer_reason"]

        results.append({
            **candidate,
            "verdict": verdict_str,
            "confidence": confidence,
            "severity": severity,
            "reason": reason,
        })

    return results


async def arbitrate_and_persist(
    db: AsyncSession,
    project_id: int,
    candidates: list[dict[str, Any]],
    llm: AsyncOpenAI,
) -> list[ContradictionOut]:
    judged = await arbitrate_candidates(candidates, llm)
    if not judged:
        return []

    results: list[ContradictionOut] = []
    for item in judged:
        contradiction = Contradiction(
            project_id=project_id,
            chapter_a_id=item["chapter_a_id"],
            chapter_b_id=item["chapter_b_id"],
            entity_id=item["entity_id"],
            field=item["field"],
            value_a=item["value_a"],
            value_b=item["value_b"],
            severity=item["severity"],
            confidence=item["confidence"],
            verdict=item["verdict"],
            reason=item["reason"],
            quote_a=item["quote_a"],
            quote_b=item["quote_b"],
        )
        db.add(contradiction)
        await db.flush()

        out = ContradictionOut.model_validate(contradiction)
        out.chapter_a_number = item["chapter_a_number"]
        out.chapter_b_number = item["chapter_b_number"]
        out.entity_name = item["entity_name"]
        results.append(out)

    return results


async def _resolve_by_alias(
    db: AsyncSession,
    project_id: int,
    extracted: EntityExtracted,
) -> Entity | None:
    candidate_names = {
        name.strip().lower()
        for name in ([extracted.canonical_name] + extracted.aliases)
        if name and name.strip()
    }
    if not candidate_names:
        return None

    result = await db.execute(
        select(Alias.entity_id, func.count(Alias.id).label("overlap"))
        .join(Entity, Alias.entity_id == Entity.id)
        .where(
            Entity.project_id == project_id,
            Entity.entity_type == extracted.entity_type,
            func.lower(Alias.raw_text).in_(candidate_names),
        )
        .group_by(Alias.entity_id)
        .order_by(func.count(Alias.id).desc(), Alias.entity_id.asc())
    )
    row = result.first()
    if row is None:
        return None
    return await db.get(Entity, row[0])


async def resolve_entity(
    db: AsyncSession,
    project_id: int,
    extracted: EntityExtracted,
) -> Entity | None:
    lookup_name = extracted.resolves_to or extracted.canonical_name
    result = await db.execute(
        select(Entity).where(
            Entity.project_id == project_id,
            Entity.canonical_name.ilike(lookup_name),
        )
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        entity = await _resolve_by_alias(db, project_id, extracted)
    return entity


async def upsert_entity(
    db: AsyncSession,
    project_id: int,
    chapter: Chapter,
    extracted: EntityExtracted,
) -> tuple[Entity, bool]:
    entity = await resolve_entity(db, project_id, extracted)

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


def build_preview_contradiction(item: dict[str, Any]) -> ContradictionOut:
    return ContradictionOut(
        id=0,
        field=item["field"],
        value_a=item["value_a"],
        value_b=item["value_b"],
        quote_a=item.get("quote_a"),
        quote_b=item.get("quote_b"),
        reason=item.get("reason"),
        severity=item["severity"],
        confidence=item["confidence"],
        verdict=item["verdict"],
        chapter_a_id=item["chapter_a_id"],
        chapter_b_id=item["chapter_b_id"],
        chapter_a_number=item.get("chapter_a_number"),
        chapter_b_number=item.get("chapter_b_number"),
        entity_id=item.get("entity_id"),
        entity_name=item.get("entity_name"),
        resolved=False,
        created_at=datetime.utcnow(),
    )
