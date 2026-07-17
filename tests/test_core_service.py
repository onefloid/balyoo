"""Core service logic, exercised against the in-memory provider (no filesystem)."""

from __future__ import annotations

import pytest
from collections_core.capabilities import Capabilities
from collections_core.errors import NotSupported, SchemaValidationError
from collections_core.models import Query
from collections_core.service import CollectionsService
from collections_schema.validator import JsonSchemaValidator
from conftest import InMemoryProvider


def _service(book_schema, **kwargs) -> CollectionsService:
    provider = InMemoryProvider(
        schemas={"books": book_schema},
        items={"books": {"dune": {"title": "Dune", "author": "Herbert"}}},
    )
    return CollectionsService(provider, JsonSchemaValidator(), **kwargs)


def test_list_collections_reports_counts_and_capabilities(book_schema):
    service = _service(book_schema)
    infos = service.list_collections()
    assert [i.name for i in infos] == ["books"]
    assert infos[0].item_count == 1
    assert infos[0].capabilities.supports_write is True


def test_create_validates_against_schema(book_schema):
    service = _service(book_schema)
    with pytest.raises(SchemaValidationError) as excinfo:
        service.create_item("books", {"author": "no title"})
    assert any("title" in message for message in excinfo.value.errors)


def test_create_persists_valid_item(book_schema):
    service = _service(book_schema)
    item = service.create_item("books", {"title": "New Book"})
    assert service.get_item("books", item.id).data["title"] == "New Book"


def test_read_only_masks_write_and_delete(book_schema):
    service = _service(book_schema, read_only=True)
    caps = service.capabilities
    assert caps.supports_read is True
    assert caps.supports_write is False
    assert caps.supports_delete is False

    with pytest.raises(NotSupported):
        service.create_item("books", {"title": "blocked"})
    with pytest.raises(NotSupported):
        service.delete_item("books", "dune")

    # Reads still work.
    assert service.list_items("books", Query()).total == 1


def test_deletable_false_masks_delete_but_keeps_write(book_schema):
    service = _service(book_schema, deletable=False)
    caps = service.capabilities
    assert caps.supports_write is True  # writes still allowed
    assert caps.supports_delete is False  # but not delete

    created = service.create_item("books", {"title": "Keeper"})
    with pytest.raises(NotSupported):
        service.delete_item("books", created.id)


def test_update_validates_merged_result(book_schema):
    service = _service(book_schema)
    with pytest.raises(SchemaValidationError):
        # Overwriting title with a non-string must fail against the merged object.
        service.update_item("books", "dune", {"title": 123})


def test_create_does_not_validate_the_id_hint(book_schema):
    # A strict schema (additionalProperties: false) must still accept a create
    # that carries an ``id`` filename hint, because ``id`` is not stored content.
    strict = {**book_schema, "additionalProperties": False}
    service = _service(strict)
    item = service.create_item("books", {"id": "hobbit", "title": "The Hobbit"})
    assert item.id == "hobbit"


def test_search_requires_search_capability(book_schema):
    provider = InMemoryProvider(
        schemas={"books": book_schema},
        items={"books": {"dune": {"title": "Dune"}}},
        capabilities=Capabilities(
            supports_read=True, supports_write=False,
            supports_delete=False, supports_search=False,
        ),
    )
    service = CollectionsService(provider, JsonSchemaValidator())

    # Plain listing needs only read and still works.
    assert service.list_items("books", Query()).total == 1
    # But a full-text query or a filter needs the (absent) search capability.
    with pytest.raises(NotSupported):
        service.list_items("books", Query(q="dune"))
    with pytest.raises(NotSupported):
        service.list_items("books", Query(filters={"title": "Dune"}))
