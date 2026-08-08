"""
Tests for POST /projects/{project_id}/extension/check,
POST /projects/{project_id}/extension/sync,
GET /projects/{project_id}/extension/status
"""
import pytest
from unittest.mock import AsyncMock, patch

async def _create_project(client, title="Novel") -> int:
    r = await client.post("/projects", json={"title": title})
    assert r.status_code == 201
    return r.json()["id"]

@pytest.mark.asyncio
async def test_extension_status_unmapped(client):
    """Status returns NOT_SYNCED for a new document."""
    pid = await _create_project(client)
    r = await client.get(f"/projects/{pid}/extension/status?document_id=doc1")
    assert r.status_code == 200
    data = r.json()
    assert data["sync_state"] == "NOT_SYNCED"
    assert data["has_synced_content"] is False
    assert data["document_id"] == "doc1"

@pytest.mark.asyncio
async def test_extension_sync_first_time(client):
    """Syncing a document for the first time creates a sync state and chapter."""
    pid = await _create_project(client)
    
    with patch("app.services.extension.cognee_service.remember", new_callable=AsyncMock) as mock_remember, \
         patch("app.services.contradiction.extract_entities", return_value=[]), \
         patch("app.services.contradiction.AsyncOpenAI"):
        
        r = await client.post(
            f"/projects/{pid}/extension/sync",
            json={
                "document_id": "doc1",
                "document_title": "My First Doc",
                "document_text": "This is a new chapter.",
                "document_revision": "rev1"
            }
        )
        assert r.status_code == 200
        data = r.json()
        assert data["sync_state"] == "SYNCED"
        assert data["sync_strategy"] == "full"
        assert len(data["chapters_created"]) == 1
        assert mock_remember.called

@pytest.mark.asyncio
async def test_extension_sync_duplicate_detection(client):
    """Syncing the same document text twice uses the 'unchanged' strategy and does not duplicate."""
    pid = await _create_project(client)
    
    payload = {
        "document_id": "doc1",
        "document_title": "My Doc",
        "document_text": "Some text to sync.",
        "document_revision": "rev1"
    }

    with patch("app.services.extension.cognee_service.remember", new_callable=AsyncMock), \
         patch("app.services.contradiction.extract_entities", return_value=[]), \
         patch("app.services.contradiction.AsyncOpenAI"):
        
        # First sync
        r1 = await client.post(f"/projects/{pid}/extension/sync", json=payload)
        assert r1.json()["sync_strategy"] == "full"
        
        # Second sync, exactly the same
        r2 = await client.post(f"/projects/{pid}/extension/sync", json=payload)
        assert r2.json()["sync_strategy"] == "unchanged"
        assert len(r2.json()["chapters_created"]) == 0

@pytest.mark.asyncio
async def test_extension_check_unchanged(client):
    """Check returns unchanged when document is already synced."""
    pid = await _create_project(client)
    
    payload = {
        "document_id": "doc1",
        "document_title": "My Doc",
        "document_text": "Text goes here.",
        "document_revision": "rev1"
    }

    with patch("app.services.extension.cognee_service.remember", new_callable=AsyncMock), \
         patch("app.services.contradiction.extract_entities", return_value=[]), \
         patch("app.services.contradiction.AsyncOpenAI"):
        
        # Sync it first
        await client.post(f"/projects/{pid}/extension/sync", json=payload)
        
        # Now check it
        r = await client.post(f"/projects/{pid}/extension/check", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["has_changes"] is False
        assert data["issue_count"] == 0

@pytest.mark.asyncio
async def test_extension_status_synced(client):
    """Status returns SYNCED if the current hash matches the synced hash."""
    pid = await _create_project(client)
    
    payload = {
        "document_id": "doc2",
        "document_text": "Hello world"
    }
    
    with patch("app.services.extension.cognee_service.remember", new_callable=AsyncMock), \
         patch("app.services.contradiction.extract_entities", return_value=[]), \
         patch("app.services.contradiction.AsyncOpenAI"):
        r_sync = await client.post(f"/projects/{pid}/extension/sync", json=payload)
        synced_hash = r_sync.json()["current_hash"]

    # Now get status
    r = await client.get(f"/projects/{pid}/extension/status?document_id=doc2&current_hash={synced_hash}")
    assert r.status_code == 200
    data = r.json()
    assert data["sync_state"] == "SYNCED"
