"""Shared test fixtures and an in-memory storage provider.

The in-memory provider proves the core is genuinely backend-agnostic: the same
``CollectionsService`` logic is exercised without touching the filesystem.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from collections_core.capabilities import Capabilities
from collections_core.errors import (
    CollectionExists,
    CollectionNotFound,
    Conflict,
    ItemNotFound,
)
from collections_core.models import Item, Page, Query

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "collections"


class InMemoryProvider:
    """A minimal in-memory ``StorageProvider`` for testing the core in isolation."""

    def __init__(
        self,
        schemas: dict[str, dict[str, Any]],
        items: dict[str, dict[str, dict[str, Any]]] | None = None,
        capabilities: Capabilities | None = None,
    ) -> None:
        self._schemas = schemas
        self._items = items or {}
        self._capabilities = capabilities or Capabilities(
            supports_read=True,
            supports_write=True,
            supports_delete=True,
            supports_search=True,
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def list_collections(self) -> list[str]:
        return sorted(self._schemas)

    def get_schema(self, collection: str) -> dict[str, Any]:
        if collection not in self._schemas:
            raise CollectionNotFound(collection)
        return self._schemas[collection]

    def create_collection(self, collection: str, schema: dict[str, Any]) -> None:
        if collection in self._schemas:
            raise CollectionExists(collection)
        self._schemas[collection] = schema

    def update_schema(self, collection: str, schema: dict[str, Any]) -> None:
        if collection not in self._schemas:
            raise CollectionNotFound(collection)
        self._schemas[collection] = schema

    def delete_collection(self, collection: str) -> None:
        if collection not in self._schemas:
            raise CollectionNotFound(collection)
        del self._schemas[collection]
        self._items.pop(collection, None)

    def list_items(self, collection: str, query: Query) -> Page[Item]:
        self.get_schema(collection)
        rows = self._items.get(collection, {})
        items = [Item(id=i, data=d) for i, d in rows.items()]
        total = len(items)
        window = items[query.offset : query.offset + query.limit]
        return Page[Item](items=window, total=total, limit=query.limit, offset=query.offset)

    def get_item(self, collection: str, item_id: str) -> Item:
        rows = self._items.get(collection, {})
        if item_id not in rows:
            raise ItemNotFound(collection, item_id)
        return Item(id=item_id, data=rows[item_id])

    def create_item(self, collection: str, data: dict[str, Any]) -> Item:
        self.get_schema(collection)
        rows = self._items.setdefault(collection, {})
        item_id = str(data.get("id") or f"item-{len(rows) + 1}")
        if item_id in rows:
            raise Conflict(f"Item already exists: {collection}/{item_id}")
        rows[item_id] = data
        return Item(id=item_id, data=data)

    def update_item(self, collection: str, item_id: str, patch: dict[str, Any]) -> Item:
        rows = self._items.get(collection, {})
        if item_id not in rows:
            raise ItemNotFound(collection, item_id)
        rows[item_id] = {**rows[item_id], **patch}
        return Item(id=item_id, data=rows[item_id])

    def delete_item(self, collection: str, item_id: str) -> None:
        rows = self._items.get(collection, {})
        if item_id not in rows:
            raise ItemNotFound(collection, item_id)
        del rows[item_id]


@pytest.fixture
def book_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Book",
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "author": {"type": "string"},
            "year": {"type": "integer"},
        },
        "required": ["title"],
    }


@pytest.fixture
def examples_copy(tmp_path: Path) -> Path:
    """A writable copy of the example collections, so tests never mutate the repo."""
    destination = tmp_path / "collections"
    shutil.copytree(EXAMPLES, destination)
    return destination


def read_item_file(root: Path, collection: str, item_id: str) -> dict[str, Any]:
    return json.loads((root / collection / "items" / f"{item_id}.json").read_text())
