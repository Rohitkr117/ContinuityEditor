import pytest
from unittest.mock import AsyncMock, patch
from app.models.schemas import EntityExtracted
from app.models.db import EntityType


@pytest.mark.asyncio
async def test_create_project(client):
    r = await client.post("/projects", json={"title": "Test Novel", "author": "Author"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test Novel"
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_ingest_chapter_no_contradictions(client):
    # Create project
    r = await client.post("/projects", json={"title": "Novel"})
    pid = r.json()["id"]

    mock_entities = [
        EntityExtracted(
            canonical_name="Alice",
            entity_type=EntityType.CHARACTER,
            aliases=["the woman"],
            attributes={"eye_color": "blue", "status": "alive"},
        )
    ]

    with patch("app.routers.chapters.cs.extract_entities", return_value=mock_entities), \
         patch("app.services.cognee_service.remember", new_callable=AsyncMock):
        r = await client.post(f"/projects/{pid}/chapters", json={
            "number": 1,
            "title": "Chapter One",
            "text": "Alice walked into the room. Her blue eyes sparkled.",
        })

    assert r.status_code == 201
    data = r.json()
    assert data["chapter_number"] == 1
    assert len(data["contradictions_found"]) == 0
    assert any(e["canonical_name"] == "Alice" for e in data["entities_extracted"])


@pytest.mark.asyncio
async def test_ingest_chapter_detects_contradiction(client):
    r = await client.post("/projects", json={"title": "Novel"})
    pid = r.json()["id"]

    ch1_entities = [EntityExtracted(
        canonical_name="Alice",
        entity_type=EntityType.CHARACTER,
        attributes={"eye_color": "blue", "status": "alive"},
    )]
    ch2_entities = [EntityExtracted(
        canonical_name="Alice",
        entity_type=EntityType.CHARACTER,
        attributes={"eye_color": "green"},  # contradiction!
    )]

    with patch("app.routers.chapters.cs.extract_entities", return_value=ch1_entities), \
         patch("app.services.cognee_service.remember", new_callable=AsyncMock):
        await client.post(f"/projects/{pid}/chapters", json={
            "number": 1, "text": "Alice has blue eyes."
        })

    with patch("app.routers.chapters.cs.extract_entities", return_value=ch2_entities), \
         patch("app.services.cognee_service.remember", new_callable=AsyncMock):
        r = await client.post(f"/projects/{pid}/chapters", json={
            "number": 2, "text": "Alice's green eyes shone in the light."
        })

    assert r.status_code == 201
    data = r.json()
    assert len(data["contradictions_found"]) == 1
    c = data["contradictions_found"][0]
    assert c["field"] == "eye_color"
    assert c["value_a"] == "blue"
    assert c["value_b"] == "green"
    # Severity is now the judge's own call rather than a hardcoded lookup, so either
    # is defensible for an unexplained eye-color change — just assert it's a real verdict.
    assert c["severity"] in ("HARD", "SOFT")
    assert c["verdict"] in ("CONFIRM", "REJECT")
    assert 0.0 <= c["confidence"] <= 1.0
