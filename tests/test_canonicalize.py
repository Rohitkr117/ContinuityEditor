"""
Tests for alias canonicalization:
  - find_alias_groups()
  - merge_entities()
  - POST /projects/{project_id}/improve
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.db import Entity, EntityType
from app.models.schemas import AliasGroup, EntityExtracted
from app.services.canonicalize import find_alias_groups, merge_entities


# ── find_alias_groups ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_alias_groups_returns_groups():
    """find_alias_groups should parse the LLM response and return AliasGroup objects."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = (
        '{"groups": [{"canonical_name": "Murphy\'s Pub", "members": ["the pub", "the bar", "Murphy\'s Pub"]}]}'
    )
    mock_llm.chat = MagicMock()
    mock_llm.chat.completions = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(return_value=mock_resp)

    groups = await find_alias_groups(mock_llm, ["the pub", "the bar", "Murphy's Pub"])

    assert len(groups) == 1
    assert groups[0].canonical_name == "Murphy's Pub"
    assert "the pub" in groups[0].aliases


@pytest.mark.asyncio
async def test_find_alias_groups_empty_input():
    """find_alias_groups returns empty list for empty input without calling the LLM."""
    mock_llm = MagicMock()
    groups = await find_alias_groups(mock_llm, [])
    assert groups == []


@pytest.mark.asyncio
async def test_find_alias_groups_llm_failure():
    """find_alias_groups returns empty list gracefully on LLM error."""
    mock_llm = MagicMock()
    mock_llm.chat.completions.create = AsyncMock(side_effect=Exception("API error"))
    groups = await find_alias_groups(mock_llm, ["Alice", "the woman"])
    assert groups == []


# ── merge_entities ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_merge_entities_merges_duplicates(db_session):
    """merge_entities should collapse two Entity rows into one canonical entity."""
    # Create two entities that should be merged
    e1 = Entity(
        project_id=1,
        canonical_name="the pub",
        entity_type=EntityType.PLACE,
        first_seen_chapter_id=None,
    )
    e1.attributes = {"description": "a dark pub"}
    e2 = Entity(
        project_id=1,
        canonical_name="Murphy's Pub",
        entity_type=EntityType.PLACE,
        first_seen_chapter_id=None,
    )
    e2.attributes = {"description": "Murphy's old pub on the corner"}
    db_session.add_all([e1, e2])
    await db_session.flush()

    group = AliasGroup(
        canonical_name="Murphy's Pub",
        aliases=["the pub", "Murphy's Pub"],
        confidence=0.95,
    )

    merged, resolved = await merge_entities(db_session, 1, [group])

    assert len(merged) == 1
    assert merged[0].canonical_name == "Murphy's Pub"
    assert resolved == 0  # no contradictions to re-point in this test


@pytest.mark.asyncio
async def test_merge_entities_skips_single_entity(db_session):
    """merge_entities skips groups where only one (or zero) entity rows match."""
    e1 = Entity(
        project_id=1,
        canonical_name="Dracula",
        entity_type=EntityType.CHARACTER,
        first_seen_chapter_id=None,
    )
    e1.attributes = {}
    db_session.add(e1)
    await db_session.flush()

    group = AliasGroup(
        canonical_name="Dracula",
        aliases=["Dracula", "the Count"],  # "the Count" doesn't exist as a separate row
        confidence=0.9,
    )

    merged, resolved = await merge_entities(db_session, 1, [group])
    assert merged == []  # nothing merged — only one entity matched


# ── improve endpoint ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_improve_empty_project(client):
    """improve on a project with no entities returns empty result."""
    r = await client.post("/projects", json={"title": "Empty Novel"})
    pid = r.json()["id"]

    with patch("app.services.cognee_service.improve", new_callable=AsyncMock), \
         patch("app.services.canonicalize.find_alias_groups", return_value=[]):
        r = await client.post(f"/projects/{pid}/improve")

    assert r.status_code == 200
    data = r.json()
    assert data["alias_groups_merged"] == []
    assert data["contradictions_resolved"] == 0


@pytest.mark.asyncio
async def test_improve_project_not_found(client):
    """improve on a non-existent project returns 404."""
    r = await client.post("/projects/99999/improve")
    assert r.status_code == 404
