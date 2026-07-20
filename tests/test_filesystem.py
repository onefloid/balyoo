"""Filesystem provider: CRUD roundtrip plus in-memory query/search/sort."""

from __future__ import annotations

import json

import pytest
from collections_core.errors import (
    CollectionExists,
    CollectionNotFound,
    Conflict,
    InvalidIdentifier,
    ItemNotFound,
)
from collections_core.models import Query
from collections_filesystem.provider import FilesystemStorageProvider
from conftest import read_item_file


def test_list_collections_and_schema(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    assert provider.list_collections() == ["books", "movies"]
    assert provider.get_schema("books")["title"] == "Book"


def test_missing_collection_raises(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    with pytest.raises(CollectionNotFound):
        provider.get_schema("does-not-exist")


def test_full_text_search(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    page = provider.list_items("books", Query(q="dune"))
    assert [item.id for item in page.items] == ["dune"]
    assert page.total == 1


def test_equality_filter(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    page = provider.list_items("books", Query(filters={"author": "Frank Herbert"}))
    assert [item.id for item in page.items] == ["dune"]


def test_sort_and_pagination(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    page = provider.list_items("books", Query(sort="year", order="asc", limit=1))
    assert page.total == 2
    assert page.items[0].id == "lotr"  # 1954 before 1965


def test_crud_roundtrip(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)

    created = provider.create_item("books", {"id": "hobbit", "title": "The Hobbit"})
    assert created.id == "hobbit"
    assert read_item_file(examples_copy, "books", "hobbit")["title"] == "The Hobbit"

    with pytest.raises(Conflict):
        provider.create_item("books", {"id": "hobbit", "title": "dup"})

    updated = provider.update_item("books", "hobbit", {"year": 1937})
    assert updated.data == {"title": "The Hobbit", "year": 1937}

    provider.delete_item("books", "hobbit")
    with pytest.raises(ItemNotFound):
        provider.get_item("books", "hobbit")


def test_create_without_id_generates_one(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    item = provider.create_item("movies", {"title": "Untitled"})
    assert item.id
    assert provider.get_item("movies", item.id).data["title"] == "Untitled"


@pytest.mark.parametrize("evil", ["../../../etc/passwd", "..", "a/b", "", ".", "x\\y"])
def test_path_traversal_ids_are_rejected(examples_copy, evil):
    provider = FilesystemStorageProvider(examples_copy)
    # A traversal id must never escape the items directory on read or delete.
    with pytest.raises(InvalidIdentifier):
        provider.get_item("books", evil)
    with pytest.raises(InvalidIdentifier):
        provider.delete_item("books", evil)


@pytest.mark.parametrize("evil", ["../../../etc/passwd", "..", "a/b", ".", "x\\y"])
def test_create_with_traversal_id_is_rejected(examples_copy, evil):
    provider = FilesystemStorageProvider(examples_copy)
    # A create must not be able to write a file outside the collection. (An empty
    # id is not a traversal risk -- it falls back to a generated uuid.)
    with pytest.raises(InvalidIdentifier):
        provider.create_item("books", {"id": evil, "title": "x"})


def test_traversal_collection_is_rejected(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    with pytest.raises(InvalidIdentifier):
        provider.get_schema("../../secret")


def test_create_collection_writes_schema_file(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    provider.create_collection("games", schema)

    assert "games" in provider.list_collections()
    assert provider.get_schema("games") == schema
    written = json.loads((examples_copy / "games" / "schema.json").read_text())
    assert written == schema


def test_create_collection_rejects_existing(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    with pytest.raises(CollectionExists):
        provider.create_collection("books", {"type": "object"})


def test_create_collection_rejects_traversal_name(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    with pytest.raises(InvalidIdentifier):
        provider.create_collection("../evil", {"type": "object"})


def test_update_schema_overwrites(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    new_schema = {"type": "object", "properties": {"title": {"type": "string"}}}

    provider.update_schema("books", new_schema)

    assert provider.get_schema("books") == new_schema


def test_update_schema_missing_collection_raises(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    with pytest.raises(CollectionNotFound):
        provider.update_schema("nope", {"type": "object"})


def test_delete_collection_removes_directory(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)

    provider.delete_collection("books")

    assert provider.list_collections() == ["movies"]
    assert not (examples_copy / "books").exists()
    with pytest.raises(CollectionNotFound):
        provider.delete_collection("books")


def test_sort_tolerates_heterogeneous_values(examples_copy):
    provider = FilesystemStorageProvider(examples_copy)
    # Mix an integer, a string and a missing value in the same sort field; the
    # old (is None, value) key would raise TypeError comparing int against str.
    provider.create_item("books", {"id": "a", "title": "A", "year": 2000})
    provider.create_item("books", {"id": "b", "title": "B", "year": "1999"})
    provider.create_item("books", {"id": "c", "title": "C"})  # no year

    page = provider.list_items("books", Query(sort="year"))
    ids = [item.id for item in page.items]
    # Does not crash, returns every item, and groups the missing value last.
    assert set(ids) == {"dune", "lotr", "a", "b", "c"}
    assert ids[-1] == "c"
