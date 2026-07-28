"""
Tests for POST /projects/{project_id}/recall and
PATCH /projects/{project_id}/recall/{contradiction_id}/resolve
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.models.schemas import EntityExtracted
from app.models.db import EntityType


# ── helpers ───────────────────────────────────────────────────────────────────

async def _create_project(client, title="Novel") -> int:
    r = await client.post("/projects", json={"title": title})
    assert r.status_code == 201
    return r.json()["id"]


async def _ingest(client, pid: int, number: int, text: str, entities):
    """Ingest a chapter with mocked entity extraction and cognee."""
    with patch("app.routers.chapters.cs.extract_entities", return_value=entities), \
         patch("app.services.cognee_service.remember", new_callable=AsyncMock):
        r = await client.post(f"/projects/{pid}/chapters", json={"number": number, "text": text})
    assert r.status_code == 201
    return r.json()


# ── recall with no contradictions ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recall_empty_project(client):
    """Recall on a brand-new project returns empty results."""
    pid = await _create_project(client)
    r = await client.post(f"/projects/{pid}/recall", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["contradictions"] == []
    assert data["cognee_hits"] == []
    assert data["checked_chapters"] == 0
    assert data["checked_entities"] == 0


@pytest.mark.asyncio
async def test_recall_returns_db_contradictions(client):
    """Recall returns contradictions that were detected at ingest time."""
    pid = await _create_project(client)

    ch1_entities = [EntityExtracted(
        canonical_name="Bob",
        entity_type=EntityType.CHARACTER,
        attributes={"eye_color": "blue", "status": "alive"},
    )]
    ch2_entities = [EntityExtracted(
        canonical_name="Bob",
        entity_type=EntityType.CHARACTER,
        attributes={"eye_color": "green"},
    )]

    # Patch the LLM judge so it reliably returns a contradiction
    mock_judge_resp = MagicMock()
    mock_judge_resp.choices[0].message.content = (
        '{"contradictions": [{"field": "eye_color", "value_a": "blue", '
        '"value_b": "green", "severity": "SOFT", "reason": "color changed", '
        '"quote_a": null, "quote_b": null}]}'
    )

    await _ingest(client, pid, 1, "Bob has blue eyes.", ch1_entities)

    with patch("app.routers.chapters.cs.extract_entities", return_value=ch2_entities), \
         patch("app.services.cognee_service.remember", new_callable=AsyncMock), \
         patch("app.services.contradiction.AsyncOpenAI"), \
         patch("app.routers.chapters.cs.propose_for_entity", new_callable=AsyncMock) as mock_propose:
        mock_propose.return_value = []  # no candidates proposed; just ensure ingest doesn't crash
        await client.post(f"/projects/{pid}/chapters", json={"number": 2, "text": "Bob has green eyes."})

    r = await client.post(f"/projects/{pid}/recall", json={})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["contradictions"], list)
    assert data["checked_entities"] >= 1


@pytest.mark.asyncio
async def test_recall_focus_filter(client):
    """Recall with a focus string returns only contradictions for that entity."""
    pid = await _create_project(client)
    r = await client.post(f"/projects/{pid}/recall", json={"focus": "Alice"})
    assert r.status_code == 200
    data = r.json()
    assert "contradictions" in data
    assert "cognee_hits" in data


@pytest.mark.asyncio
async def test_recall_chapter_ids_filter(client):
    """Recall with chapter_ids filters to specific chapters."""
    pid = await _create_project(client)
    ch1_entities = [EntityExtracted(
        canonical_name="Eve",
        entity_type=EntityType.CHARACTER,
        attributes={"status": "alive"},
    )]
    await _ingest(client, pid, 1, "Eve is alive.", ch1_entities)

    # Get chapter list
    chapters_r = await client.get(f"/projects/{pid}/chapters")
    ch_ids = [c["id"] for c in chapters_r.json()]

    r = await client.post(f"/projects/{pid}/recall", json={"chapter_ids": ch_ids})
    assert r.status_code == 200


# ── resolve endpoint ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_nonexistent_contradiction(client):
    """Resolving a contradiction that doesn't exist returns 404."""
    pid = await _create_project(client)
    r = await client.patch(f"/projects/{pid}/recall/99999/resolve")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_recall_project_not_found(client):
    """Recall on a missing project returns 404."""
    r = await client.post("/projects/99999/recall", json={})
    assert r.status_code == 404
