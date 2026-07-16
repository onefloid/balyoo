"""Core service logic, exercised against the in-memory provider (no filesystem)."""

from __future__ import annotations

import pytest
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


def test_update_validates_merged_result(book_schema):
    service = _service(book_schema)
    with pytest.raises(SchemaValidationError):
        # Overwriting title with a non-string must fail against the merged object.
        service.update_item("books", "dune", {"title": 123})
