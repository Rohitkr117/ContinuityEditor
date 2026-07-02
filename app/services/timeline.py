"""
Timeline extraction — ask the LLM to pull narrative events directly from each
chapter's raw text, then order them chronologically and detect gaps.
"""
from __future__ import annotations
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db import Chapter
from app.models.schemas import TimelineEvent, TimelineResponse

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """\
You are a continuity analyst for fiction manuscripts.
Given a chapter number and its text, extract every datable or sequenceable narrative event.
An event is anything that happens in the story world: arrivals, departures, deaths, meetings,
discoveries, letters sent/received, journeys, etc.

Return JSON:
{
  "events": [
    {
      "description": "one-sentence summary of the event",
      "raw_date_mention": "exact date/time phrase from text, or null",
      "order_hint": "early|middle|late"
    }
  ]
}
Only include story-world events, not narration. Be thorough — prefer more events over fewer."""

_ORDER_SYSTEM = """\
You are a continuity analyst. Given a list of narrative events from a fiction manuscript
(each tagged with chapter number and position hint), do two things:
1. Sort them into the most likely in-story chronological order.
2. Identify any gaps or impossibilities (character in two places, event before its cause,
   impossible travel times, resurrection without explanation, etc.).

Return JSON:
{
  "ordered_events": [
    {
      "description": "...",
      "chapter_number": N,
      "order_confidence": 0.0-1.0,
      "raw_date_mention": "..." or null
    }
  ],
  "gaps": ["description of gap or impossibility", ...]
}"""


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        stripped = raw.lstrip().lstrip("{").lstrip()
        return json.loads(stripped)


async def _extract_chapter_events(
    llm: AsyncOpenAI, chapter: Chapter
) -> list[dict]:
    """Pull narrative events from a single chapter."""
    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"Chapter {chapter.number}:\n\n{chapter.raw_text[:8000]}"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = _parse_json(resp.choices[0].message.content or "{}")
        events = data.get("events", [])
        for e in events:
            e["chapter_number"] = chapter.number
            e["chapter_id"] = chapter.id
        return events
    except Exception as exc:
        logger.warning("Timeline extraction failed for ch.%s: %s", chapter.number, exc)
        return []


async def build_timeline(
    db: AsyncSession, llm: AsyncOpenAI, project_id: int
) -> TimelineResponse:
    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.number)
    )
    chapters = chapters_result.scalars().all()

    if not chapters:
        return TimelineResponse(events=[], gaps_detected=[])

    # Extract events from every chapter
    all_raw: list[dict] = []
    for chapter in chapters:
        chapter_events = await _extract_chapter_events(llm, chapter)
        all_raw.extend(chapter_events)

    if not all_raw:
        return TimelineResponse(events=[], gaps_detected=[])

    # Pass the full event list to the ordering LLM
    try:
        resp = await llm.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _ORDER_SYSTEM},
                {"role": "user", "content": json.dumps(all_raw)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = _parse_json(resp.choices[0].message.content or "{}")
    except Exception as exc:
        logger.warning("Timeline ordering failed: %s", exc)
        data = {}

    # Build chapter_id lookup by chapter number
    ch_id_by_num = {c.number: c.id for c in chapters}

    ordered = data.get("ordered_events", all_raw)
    gaps = data.get("gaps", [])

    events: list[TimelineEvent] = []
    for item in ordered:
        ch_num = item.get("chapter_number", 0)
        events.append(TimelineEvent(
            entity_id=None,
            description=item.get("description", ""),
            chapter_id=ch_id_by_num.get(ch_num, 0),
            chapter_number=ch_num,
            order_confidence=item.get("order_confidence", 0.5),
            raw_date_mention=item.get("raw_date_mention"),
        ))

    return TimelineResponse(events=events, gaps_detected=gaps)
