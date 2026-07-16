"""Filesystem provider: CRUD roundtrip plus in-memory query/search/sort."""

from __future__ import annotations

import pytest
from collections_core.errors import CollectionNotFound, Conflict, ItemNotFound
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
