"""Deterministic upsert gate for `collections ingest`."""

from __future__ import annotations

import pytest
from collections_cli.ingest import UpsertPlan, plan_upsert, resolve_slug, slugify
from collections_core.errors import CollectionNotFound, SchemaValidationError
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_schema.validator import JsonSchemaValidator


def _service(root) -> CollectionsService:
    return CollectionsService(
        FilesystemStorageProvider(root), JsonSchemaValidator(), read_only=False
    )


def test_slugify_normalizes():
    assert slugify("Cool Bar!") == "cool-bar"
    assert slugify("  The Lord of the Rings  ") == "the-lord-of-the-rings"


def test_resolve_slug_precedence():
    assert resolve_slug({"title": "Dune"}, "Explicit Id") == "explicit-id"
    assert resolve_slug({"name": "A Place", "title": "ignored"}) == "a-place"
    assert resolve_slug({"title": "Dune"}) == "dune"
    generated = resolve_slug({"pages": 100})
    assert generated and generated.isalnum()


def test_plan_create_for_new_item(examples_copy):
    service = _service(examples_copy)
    plan = plan_upsert(service, "books", "the-hobbit", {"title": "The Hobbit"})
    assert isinstance(plan, UpsertPlan)
    assert plan.action == "create"
    assert plan.target == {"title": "The Hobbit"}
    assert plan.changes == []


def test_plan_update_produces_diff(examples_copy):
    service = _service(examples_copy)
    plan = plan_upsert(service, "books", "dune", {"pages": 500, "rating": 5})
    assert plan.action == "update"
    # Existing fields are preserved; the patch is merged on top.
    assert plan.target["title"] == "Dune"
    assert plan.target["pages"] == 500
    assert any("pages" in c and "412" in c for c in plan.changes)
    assert any(c.startswith("+ rating") for c in plan.changes)


def test_plan_rejects_invalid_item(examples_copy):
    service = _service(examples_copy)
    with pytest.raises(SchemaValidationError):
        plan_upsert(service, "books", "no-title", {"author": "nobody"})


def test_plan_unknown_collection(examples_copy):
    service = _service(examples_copy)
    with pytest.raises(CollectionNotFound):
        plan_upsert(service, "nope", "x", {"title": "x"})


def test_id_is_metadata_not_stored(examples_copy):
    service = _service(examples_copy)
    plan = plan_upsert(service, "books", "hobbit", {"id": "hobbit", "title": "The Hobbit"})
    assert "id" not in plan.target  # id names the file; it is not item data


def test_end_to_end_create_then_update(examples_copy):
    service = _service(examples_copy)

    plan = plan_upsert(service, "books", "the-hobbit", {"title": "The Hobbit"})
    service.create_item("books", {"title": "The Hobbit", "id": plan.slug})
    assert service.get_item("books", "the-hobbit").data["title"] == "The Hobbit"

    update = plan_upsert(service, "books", "the-hobbit", {"year": 1937})
    assert update.action == "update"
    service.update_item("books", "the-hobbit", {"year": 1937})
    stored = service.get_item("books", "the-hobbit").data
    assert stored == {"title": "The Hobbit", "year": 1937}
