"""MCP tool layer: schema-typed tools, capability gating, and dispatch/errors."""

from __future__ import annotations

import pytest
from collections_core.errors import (
    CollectionNotFound,
    NotSupported,
    SchemaValidationError,
)
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_mcp.server import build_tools, dispatch
from collections_schema.validator import JsonSchemaValidator
from conftest import InMemoryProvider


def _mem(book_schema, **kwargs) -> CollectionsService:
    provider = InMemoryProvider(
        schemas={"books": book_schema},
        items={"books": {"dune": {"title": "Dune", "author": "Herbert"}}},
    )
    return CollectionsService(provider, JsonSchemaValidator(), **kwargs)


def _fs(root, **kwargs) -> CollectionsService:
    return CollectionsService(
        FilesystemStorageProvider(root), JsonSchemaValidator(), **kwargs
    )


# -- tool generation ---------------------------------------------------------
def test_generic_and_per_collection_tools(book_schema):
    names = [t.name for t in build_tools(_mem(book_schema))]
    assert {
        "list_collections",
        "get_schema",
        "list_items",
        "get_item",
        "create_books",
        "update_books",
        "delete_item",
    } <= set(names)


def test_write_tool_input_schema_is_the_collection_schema(book_schema):
    tools = {t.name: t for t in build_tools(_mem(book_schema))}

    create = tools["create_books"].inputSchema
    assert {"title", "author", "year"} <= set(create["properties"])
    assert create["required"] == ["title"]

    update = tools["update_books"].inputSchema
    assert update["required"] == ["id"]  # only id required for a partial patch
    assert "id" in update["properties"]


def test_write_tools_strip_presentation_keywords():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "x-card": {"title": "title"},
        "x-collection": {"icon": "📚"},
    }
    provider = InMemoryProvider(schemas={"books": schema})
    tools = {t.name: t for t in build_tools(CollectionsService(provider))}
    create = tools["create_books"].inputSchema
    assert "x-card" not in create and "x-collection" not in create and "$schema" not in create


def test_read_only_service_exposes_no_write_tools(book_schema):
    names = [t.name for t in build_tools(_mem(book_schema, read_only=True))]
    assert not any(n.startswith(("create_", "update_")) for n in names)
    assert "delete_item" not in names
    assert {"list_collections", "list_items", "get_item"} <= set(names)


# -- dispatch (against the real filesystem provider) -------------------------
def test_dispatch_full_crud_and_search(examples_copy):
    svc = _fs(examples_copy)

    created = dispatch(svc, "create_books", {"id": "hobbit", "title": "The Hobbit"})
    assert created["id"] == "hobbit"
    assert created["data"]["title"] == "The Hobbit"

    got = dispatch(svc, "get_item", {"collection": "books", "id": "hobbit"})
    assert got["data"]["title"] == "The Hobbit"

    page = dispatch(svc, "list_items", {"collection": "books", "q": "hobbit"})
    assert page["total"] == 1
    assert page["items"][0]["id"] == "hobbit"

    updated = dispatch(svc, "update_books", {"id": "hobbit", "year": 1937})
    assert updated["data"] == {"title": "The Hobbit", "year": 1937}

    assert dispatch(svc, "delete_item", {"collection": "books", "id": "hobbit"}) == {
        "deleted": "books/hobbit"
    }


def test_list_collections_reports_names(examples_copy):
    result = dispatch(_fs(examples_copy), "list_collections", {})
    assert {c["name"] for c in result} == {"books", "movies"}


def test_dispatch_maps_domain_errors(examples_copy):
    svc = _fs(examples_copy)
    with pytest.raises(CollectionNotFound):
        dispatch(svc, "get_schema", {"collection": "nope"})
    with pytest.raises(SchemaValidationError):
        dispatch(svc, "create_books", {"author": "no title"})


def test_dispatch_write_blocked_when_read_only(examples_copy):
    with pytest.raises(NotSupported):
        dispatch(_fs(examples_copy, read_only=True), "create_books", {"title": "x"})


def test_unknown_tool_raises(examples_copy):
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch(_fs(examples_copy), "frobnicate", {})
