"""SQLite provider: CRUD roundtrip, query engine parity, and service integration."""

from __future__ import annotations

import pytest
from collections_core.errors import (
    CollectionNotFound,
    Conflict,
    ItemNotFound,
    NotSupported,
    SchemaValidationError,
)
from collections_core.models import Query
from collections_core.service import CollectionsService
from collections_schema.validator import JsonSchemaValidator
from collections_sqlite.provider import SqliteStorageProvider

BOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "author": {"type": "string"},
        "year": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title"],
}


def _provider(tmp_path) -> SqliteStorageProvider:
    provider = SqliteStorageProvider(tmp_path / "c.db")
    provider.create_collection("books", BOOK_SCHEMA)
    provider.create_item(
        "books", {"id": "dune", "title": "Dune", "author": "Herbert", "year": 1965}
    )
    provider.create_item(
        "books", {"id": "lotr", "title": "The Lord of the Rings", "year": 1954}
    )
    return provider


def test_capabilities_include_transactions(tmp_path):
    caps = SqliteStorageProvider(tmp_path / "c.db").capabilities
    assert caps.supports_write and caps.supports_delete and caps.supports_transactions


def test_list_collections_and_schema(tmp_path):
    provider = _provider(tmp_path)
    assert provider.list_collections() == ["books"]
    assert provider.get_schema("books")["required"] == ["title"]


def test_missing_collection_raises(tmp_path):
    with pytest.raises(CollectionNotFound):
        SqliteStorageProvider(tmp_path / "c.db").get_schema("nope")


def test_crud_roundtrip(tmp_path):
    provider = _provider(tmp_path)

    created = provider.create_item("books", {"id": "hobbit", "title": "The Hobbit"})
    assert created.id == "hobbit"
    assert provider.get_item("books", "hobbit").data["title"] == "The Hobbit"

    with pytest.raises(Conflict):
        provider.create_item("books", {"id": "hobbit", "title": "dup"})

    updated = provider.update_item("books", "hobbit", {"year": 1937})
    assert updated.data == {"title": "The Hobbit", "year": 1937}

    provider.delete_item("books", "hobbit")
    with pytest.raises(ItemNotFound):
        provider.get_item("books", "hobbit")
    with pytest.raises(ItemNotFound):
        provider.delete_item("books", "hobbit")


def test_create_without_id_generates_one(tmp_path):
    provider = _provider(tmp_path)
    item = provider.create_item("books", {"title": "Untitled"})
    assert item.id and provider.get_item("books", item.id).data["title"] == "Untitled"


def test_create_in_unknown_collection_raises(tmp_path):
    with pytest.raises(CollectionNotFound):
        SqliteStorageProvider(tmp_path / "c.db").create_item("ghost", {"title": "x"})


def test_search_sort_and_pagination(tmp_path):
    provider = _provider(tmp_path)

    hits = provider.list_items("books", Query(q="lord"))
    assert [i.id for i in hits.items] == ["lotr"]

    page = provider.list_items("books", Query(sort="year", order="asc", limit=1))
    assert page.total == 2
    assert page.items[0].id == "lotr"  # 1954 before 1965


def test_works_as_a_drop_in_service_backend(tmp_path):
    provider = _provider(tmp_path)
    service = CollectionsService(provider, JsonSchemaValidator())

    with pytest.raises(SchemaValidationError):
        service.create_item("books", {"author": "no title"})  # schema-invalid

    item = service.create_item("books", {"title": "Valid"})
    assert service.get_item("books", item.id).data["title"] == "Valid"

    # read-only masks writes on the very same provider
    ro = CollectionsService(provider, JsonSchemaValidator(), read_only=True)
    with pytest.raises(NotSupported):
        ro.delete_item("books", item.id)


def test_persists_across_reopen(tmp_path):
    db = tmp_path / "c.db"
    provider = SqliteStorageProvider(db)
    provider.create_collection("books", BOOK_SCHEMA)
    provider.create_item("books", {"id": "keep", "title": "Kept"})

    reopened = SqliteStorageProvider(db)
    assert reopened.get_item("books", "keep").data["title"] == "Kept"


def test_cli_migrate_seeds_a_database_from_a_filesystem_root(examples_copy, tmp_path):
    from collections_cli.main import migrate

    db = tmp_path / "c.db"
    migrate(db=db, root=examples_copy)

    provider = SqliteStorageProvider(db)
    assert provider.list_collections() == ["books", "movies"]
    assert provider.get_item("books", "dune").data["title"] == "Dune"

    # Idempotent: a second run doesn't duplicate or error.
    migrate(db=db, root=examples_copy)
    assert provider.list_items("books", Query(limit=100)).total == 2
