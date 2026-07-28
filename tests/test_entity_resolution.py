"""
Tests for entity resolution during upsert_entity() — specifically the
alias-table fallback in app.services.contradiction._resolve_by_alias.

Without this fallback, when the extraction LLM invents a slightly different
canonical name for an entity it already knows about (without setting
resolves_to), upsert_entity silently creates a duplicate Entity row and the
contradiction check never runs for it at all — a false negative with no
visible trace. See scripts/eval_contradictions.py's "dead man walking" case,
which is exactly this failure mode.
"""
import pytest

from app.models.db import Chapter, EntityType
from app.models.schemas import EntityExtracted
from app.services.contradiction import upsert_entity


@pytest.mark.asyncio
async def test_upsert_entity_resolves_via_shared_alias(db_session):
    """
    Chapter 1 introduces 'Old Tomas' (alias 'Tomas'). Chapter 2's extraction
    invents a new canonical name 'Tomas the blacksmith' (also aliased 'Tomas')
    without setting resolves_to. The alias-table fallback should still resolve
    this to the SAME entity rather than creating a duplicate.
    """
    chapter1 = Chapter(project_id=1, number=1, raw_text="Old Tomas fell from the tower.")
    db_session.add(chapter1)
    await db_session.flush()

    first = EntityExtracted(
        canonical_name="Old Tomas",
        entity_type=EntityType.CHARACTER,
        aliases=["Tomas", "the blacksmith"],
        attributes={"status": "dead"},
    )
    entity1, is_new1 = await upsert_entity(db_session, 1, chapter1, first)
    assert is_new1 is True

    chapter2 = Chapter(project_id=1, number=2, raw_text="Tomas hammered at his forge.")
    db_session.add(chapter2)
    await db_session.flush()

    second = EntityExtracted(
        canonical_name="Tomas the blacksmith",
        entity_type=EntityType.CHARACTER,
        aliases=["Tomas", "the blacksmith"],
        attributes={"status": "alive"},
        resolves_to=None,
    )
    entity2, is_new2 = await upsert_entity(db_session, 1, chapter2, second)

    assert is_new2 is False
    assert entity2.id == entity1.id


@pytest.mark.asyncio
async def test_upsert_entity_does_not_cross_entity_types(db_session):
    """A PLACE and a CHARACTER sharing an alias string must not be merged."""
    chapter1 = Chapter(project_id=1, number=1, raw_text="The Rose was a fine tavern where Rose worked.")
    db_session.add(chapter1)
    await db_session.flush()

    place = EntityExtracted(
        canonical_name="The Rose",
        entity_type=EntityType.PLACE,
        aliases=["Rose"],
        attributes={},
    )
    await upsert_entity(db_session, 1, chapter1, place)

    character = EntityExtracted(
        canonical_name="Rose Tyler",
        entity_type=EntityType.CHARACTER,
        aliases=["Rose"],
        attributes={},
    )
    entity, is_new = await upsert_entity(db_session, 1, chapter1, character)

    assert is_new is True


@pytest.mark.asyncio
async def test_upsert_entity_exact_canonical_match_still_wins(db_session):
    """An exact canonical_name match should resolve without needing the alias fallback."""
    chapter1 = Chapter(project_id=1, number=1, raw_text="Alice appeared.")
    db_session.add(chapter1)
    await db_session.flush()

    first = EntityExtracted(
        canonical_name="Alice",
        entity_type=EntityType.CHARACTER,
        aliases=[],
        attributes={"eye_color": "blue"},
    )
    entity1, _ = await upsert_entity(db_session, 1, chapter1, first)

    second = EntityExtracted(
        canonical_name="Alice",
        entity_type=EntityType.CHARACTER,
        aliases=[],
        attributes={"eye_color": "green"},
    )
    entity2, is_new2 = await upsert_entity(db_session, 1, chapter1, second)

    assert is_new2 is False
    assert entity2.id == entity1.id
