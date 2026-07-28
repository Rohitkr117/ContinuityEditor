"""
Contradiction detection pipeline — multi-agent proposer/arbiter design.

  propose_for_entity() - one "analyst" agent per entity, run in parallel across all
                          entities touched by a chapter. Each only sees that entity's
                          own attributes + the chapter text it appeared in, and must
                          self-report a confidence score for every candidate it raises.
  arbitrate_and_persist() - one final "judge" agent per chapter ingest. Reviews every
                          candidate proposed across all entities using ONLY the
                          structured evidence (no raw prose) and rules CONFIRM/REJECT
                          with its own confidence. Every candidate is persisted, pass
                          or reject, so the pipeline's reasoning stays inspectable.

Quote evidence is verified programmatically against the actual chapter text before it
ever reaches the arbiter — an LLM-invented quote that doesn't appear in the source is
nulled out rather than trusted.
"""
from __future__ import annotations
import difflib
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import func, select
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
    """
    Tolerantly parse a model's JSON response. This free-tier model is prone to two
    distinct formatting quirks even with response_format=json_object: wrapping the
    real object in a stray extra leading '{', and appending trailing garbage after
    an otherwise-complete object ("Extra data" from json.loads). Handle both rather
    than silently discarding a valid answer as a parse failure.
    """
    candidates = [raw, raw.lstrip().lstrip("{").lstrip()]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # Last resort: parse just the first complete JSON value and ignore anything
    # the model appended after it.
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


# ── Proposer agent (per-entity) ─────────────────────────────────────────────────

_PROPOSER_SYSTEM = """\
You are a continuity analyst for fiction manuscripts. You receive one entity's known
attributes from previous chapters and the changed/new attributes observed in the latest
chapter, plus the raw text of both so you can find exact evidence quotes.

A genuine contradiction is a pair of facts about the SAME entity that cannot both be true
at the same time, with no plausible in-story explanation available in the text (e.g.
death, disguise, injury/healing, deliberate change, the passage of time). Judge each
attribute change on its underlying meaning, not surface wording — rephrasing, added
detail, or ambiguous wording alone are not contradictions.

You are the first stage of a two-stage pipeline: a separate judge will review every
candidate you raise before anything is shown to the writer, using only what you report
here. Raise anything plausible, but you MUST self-assess how confident you are that it
is a genuine, narratively-unexplained contradiction:
  0.8-1.0 = both values are explicit and directly conflict; no plausible explanation in the text
  0.5-0.79 = values plausibly conflict but wording, context, or partial evidence leaves room for doubt
  0.0-0.49 = weak or speculative — do not include these at all

=== Severity (your best assessment; the downstream judge makes the final call) ===
- HARD: the two states are mutually exclusive with no plausible explanation (e.g.
  simultaneously alive and confirmed dead, or a destroyed object appearing intact)
- SOFT: inconsistent but plausibly explainable by ordinary narrative drift (e.g. a
  sensory/descriptive detail differing slightly)

=== Evidence quotes ===
For each candidate, find the shortest exact sentence or phrase from each chapter's raw
text that best supports the flagged value. Use null if you cannot find a clear quote —
never invent a quote that doesn't appear in the text; a fabricated quote will be caught
and discarded automatically, so there is nothing to gain by guessing one.

Return ONLY this JSON — no prose:
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

# Values the extraction LLM writes when an attribute is not mentioned in the chapter.
# These should be treated as "absent" — never as a real value to compare against.
_NULL_LIKE = frozenset({
    "none", "null", "unknown", "n/a", "na", "not mentioned",
    "not specified", "not stated", "unspecified", "",
})

# Known equivalent spellings/phrasings that should never be treated as a changed value.
_SYNONYM_VALUES = {
    "grey": "gray",
}


def _is_null_like(value: Any) -> bool:
    """Return True if *value* is a null-like placeholder (not a real fact)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULL_LIKE:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _strip_null_like(attrs: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively remove null-like values from an attribute dict.

    For nested dicts (e.g. relationships: {suitor_of: "none"}), strips null-like
    sub-keys and removes the parent key entirely if the dict becomes empty.
    """
    cleaned: dict[str, Any] = {}
    for k, v in attrs.items():
        if isinstance(v, dict):
            inner = {ik: iv for ik, iv in v.items() if not _is_null_like(iv)}
            if inner:
                cleaned[k] = inner
        elif not _is_null_like(v):
            cleaned[k] = v
    return cleaned


def _normalize_value(v: Any) -> str:
    """Normalize a value for equality comparison so trivial rewording/casing/whitespace
    doesn't get sent to the proposer as a 'changed' field in the first place."""
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, sort_keys=True)
        except TypeError:
            return str(v)
    s = re.sub(r"\s+", " ", str(v).strip().lower())
    return _SYNONYM_VALUES.get(s, s)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _quote_is_grounded(quote: str | None, source_text: str, threshold: float = 0.85) -> bool:
    """
    True if *quote* verifiably appears (verbatim or near-verbatim) in *source_text*.

    Guards against the proposer inventing evidence that isn't actually in the chapter —
    a fabricated quote is the single most convincing-looking form of hallucination this
    pipeline can produce, so it is checked in code rather than trusted from the model.
    """
    if not quote:
        return False
    q = _normalize_text(quote)
    if len(q) < 3:
        return False
    t = _normalize_text(source_text)
    if q in t:
        return True
    matcher = difflib.SequenceMatcher(None, q, t)
    match = matcher.find_longest_match(0, len(q), 0, len(t))
    return (match.size / len(q)) >= threshold


async def propose_for_entity(
    previous_chapters: list[Chapter],
    chapter_b: Chapter,
    entity: Entity,
    existing_attributes: dict[str, Any],
    incoming_attributes: dict[str, Any],
    llm: AsyncOpenAI,
) -> list[dict[str, Any]]:
    """
    Per-entity proposer agent. Meant to be run concurrently (asyncio.gather) across all
    entities touched by a chapter ingest, after every entity's attributes for this
    chapter have already been merged — so *existing_attributes* must be a snapshot taken
    BEFORE the merge, not re-read from entity.attributes (which would already equal the
    incoming values by then). Returns candidate dicts — nothing is persisted here; the
    final arbiter decides what survives.
    """
    existing = existing_attributes
    if not existing or not incoming_attributes:
        return []

    cleaned_incoming = _strip_null_like(incoming_attributes)
    if not cleaned_incoming:
        return []

    # Deterministic pre-filter: only ask the LLM about fields that actually changed
    # (after normalization). Removes a whole class of hallucinated "contradictions"
    # on values that are identical or trivially reworded.
    changed_or_new = {
        k: v for k, v in cleaned_incoming.items()
        if k not in existing or _normalize_value(existing[k]) != _normalize_value(v)
    }
    if not changed_or_new:
        return []

    texts_a = []
    for ch in previous_chapters:
        texts_a.append(f"--- Chapter {ch.number} raw text (truncated) ---\n{(ch.raw_text or '')[:4000]}")
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
    for cand in raw_candidates:
        chapter_a_num = cand.get("chapter_a_number")
        ch_a = None
        if chapter_a_num is not None:
            try:
                ch_a = next((c for c in previous_chapters if c.number == int(chapter_a_num)), None)
            except (ValueError, TypeError):
                pass
        if not ch_a:
            ch_a = previous_chapters[0]  # default to first seen / earliest available

        quote_a = cand.get("quote_a") or None
        quote_b = cand.get("quote_b") or None
        quote_a_grounded = _quote_is_grounded(quote_a, ch_a.raw_text or "")
        quote_b_grounded = _quote_is_grounded(quote_b, chapter_b.raw_text or "")
        if quote_a and not quote_a_grounded:
            logger.warning(
                "Proposer produced an ungrounded quote_a for %s/%s: %r",
                entity.canonical_name, cand.get("field"), quote_a,
            )
            quote_a = None
        if quote_b and not quote_b_grounded:
            logger.warning(
                "Proposer produced an ungrounded quote_b for %s/%s: %r",
                entity.canonical_name, cand.get("field"), quote_b,
            )
            quote_b = None

        try:
            confidence = float(cand.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        sev_str = str(cand.get("severity", "SOFT")).upper()
        proposer_severity = Severity.HARD if sev_str == "HARD" else Severity.SOFT

        candidates.append({
            "entity_id": entity.id,
            "entity_name": entity.canonical_name,
            "field": cand.get("field", "unknown"),
            "value_a": str(cand.get("value_a", "")),
            "value_b": str(cand.get("value_b", "")),
            "proposer_severity": proposer_severity,
            "proposer_confidence": confidence,
            "proposer_reason": cand.get("reason") or None,
            "quote_a": quote_a,
            "quote_b": quote_b,
            "quote_a_grounded": quote_a_grounded,
            "quote_b_grounded": quote_b_grounded,
            "chapter_a_id": ch_a.id,
            "chapter_a_number": ch_a.number,
            "chapter_b_id": chapter_b.id,
            "chapter_b_number": chapter_b.number,
        })

    return candidates


# ── Arbiter agent (final judge, one call per chapter ingest) ────────────────────

_ARBITER_SYSTEM = """\
You are the final arbiter in a continuity-detection pipeline for fiction manuscripts.
Several per-entity analyst agents have each proposed candidate contradictions. You do
NOT have access to the original chapter text — you must judge each candidate using only
the structured evidence given: the field, the two conflicting values, the proposer's
severity/confidence/reason, the evidence quotes (if any), and whether each quote was
independently verified as appearing in the source chapter.

For each candidate, decide:
  - verdict: "CONFIRM" if this is a genuine, narratively-unexplained contradiction worth
    surfacing to the writer; "REJECT" if the two values are plausibly compatible, too
    weakly evidenced, or too ambiguous to assert as a contradiction.
  - confidence: your own 0.0-1.0 confidence in this verdict. Weigh quote verification
    heavily — an unverified or missing quote on either side should pull confidence down,
    since there is no independently-checked evidence backing the claim.
  - severity: "HARD" or "SOFT" — your own assessment (you may agree or disagree with the
    proposer). Fill it in even when rejecting, as your best guess.
  - reason: one sentence justifying the verdict.

Be skeptical by default — the proposer stage is allowed to over-generate; your job is to
filter it down. When in doubt between CONFIRM and REJECT, prefer REJECT with a mid-range
confidence rather than CONFIRM with low confidence.

Input is a JSON array of candidates, each with an "id". Return ONLY this JSON — no prose:
{
  "verdicts": [
    {"id": 0, "verdict": "CONFIRM or REJECT", "confidence": 0.0, "severity": "HARD or SOFT", "reason": "..."}
  ]
}
Return exactly one verdict per candidate id."""


async def arbitrate_and_persist(
    db: AsyncSession,
    project_id: int,
    candidates: list[dict[str, Any]],
    llm: AsyncOpenAI,
) -> list[ContradictionOut]:
    """
    Final judge stage — one call per chapter ingest, reviewing every candidate proposed
    across all entities. Every candidate is persisted (CONFIRM or REJECT) with the
    arbiter's confidence, so the pipeline's reasoning stays inspectable rather than
    silently dropping what it filters out.
    """
    if not candidates:
        return []

    payload = [
        {
            "id": i,
            "entity": c["entity_name"],
            "field": c["field"],
            "value_a": c["value_a"],
            "value_b": c["value_b"],
            "proposer_severity": c["proposer_severity"].value,
            "proposer_confidence": c["proposer_confidence"],
            "proposer_reason": c["proposer_reason"],
            "quote_a": c["quote_a"],
            "quote_b": c["quote_b"],
            "quote_a_verified": c["quote_a_grounded"],
            "quote_b_verified": c["quote_b_grounded"],
        }
        for i, c in enumerate(candidates)
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
        for v in data.get("verdicts", []):
            try:
                idx = int(v.get("id"))
            except (TypeError, ValueError):
                continue
            verdicts[idx] = v
    except Exception as exc:
        logger.warning("Arbiter call failed, rejecting all %d candidate(s): %s", len(candidates), exc)

    results: list[ContradictionOut] = []
    for i, cand in enumerate(candidates):
        v = verdicts.get(i)
        if v is None:
            # Fail safe: no verdict came back for this candidate — reject rather than
            # silently confirming something the arbiter never actually reviewed.
            verdict_str = "REJECT"
            confidence = 0.0
            severity = cand["proposer_severity"]
            reason = cand["proposer_reason"] or "no arbiter verdict returned"
        else:
            verdict_str = "CONFIRM" if str(v.get("verdict", "REJECT")).upper() == "CONFIRM" else "REJECT"
            try:
                confidence = max(0.0, min(1.0, float(v.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            sev_str = str(v.get("severity", cand["proposer_severity"].value)).upper()
            severity = Severity.HARD if sev_str == "HARD" else Severity.SOFT
            reason = v.get("reason") or cand["proposer_reason"]

        c = Contradiction(
            project_id=project_id,
            chapter_a_id=cand["chapter_a_id"],
            chapter_b_id=cand["chapter_b_id"],
            entity_id=cand["entity_id"],
            field=cand["field"],
            value_a=cand["value_a"],
            value_b=cand["value_b"],
            severity=severity,
            confidence=confidence,
            verdict=verdict_str,
            reason=reason,
            quote_a=cand["quote_a"],
            quote_b=cand["quote_b"],
        )
        db.add(c)
        await db.flush()

        out = ContradictionOut.model_validate(c)
        out.chapter_a_number = cand["chapter_a_number"]
        out.chapter_b_number = cand["chapter_b_number"]
        results.append(out)

    return results


async def _resolve_by_alias(
    db: AsyncSession,
    project_id: int,
    extracted: EntityExtracted,
) -> Entity | None:
    """
    Fallback resolution when resolves_to is unset and the canonical name doesn't
    match anything: check whether the extracted canonical name or any of its
    aliases were already recorded as an alias of an existing entity of the same
    type in this project.

    This catches the extraction LLM inventing a slightly different canonical
    name for an entity it already knows about (e.g. "Tomas the blacksmith" vs
    "Old Tomas") without setting resolves_to. Left unhandled, that silently
    spawns a duplicate Entity row and the contradiction check never runs at all
    for that entity — a much more damaging failure than a false positive, since
    it produces a false negative with no visible trace.

    Scoped to entity_type so, e.g., a PLACE and a CHARACTER sharing a generic
    alias string are never merged into each other.
    """
    candidate_names = {
        n.strip().lower() for n in ([extracted.canonical_name] + extracted.aliases)
        if n and n.strip()
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


async def upsert_entity(
    db: AsyncSession,
    project_id: int,
    chapter: Chapter,
    extracted: EntityExtracted,
) -> tuple[Entity, bool]:
    """
    Find or create an entity. Returns (entity, is_new).

    Resolution order:
      1. extracted.resolves_to, if the LLM set it, or an exact canonical_name match
      2. alias-table fallback (see _resolve_by_alias) for when the LLM invented a
         new canonical name without setting resolves_to
    """
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
