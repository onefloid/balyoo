"""Filesystem-backed :class:`~collections_core.interfaces.StorageProvider`."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from collections_core.capabilities import Capabilities
from collections_core.errors import CollectionNotFound, Conflict, ItemNotFound
from collections_core.models import Item, Page, Query


class FilesystemStorageProvider:
    """Stores each item as a JSON file under ``<root>/<collection>/items``.

    Filtering, full-text search, sorting and pagination are applied in memory,
    so no external search backend is required for the default deployment.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_read=True,
            supports_write=True,
            supports_delete=True,
            supports_search=True,
            supports_transactions=False,
        )

    # -- layout helpers --------------------------------------------------
    def _collection_dir(self, collection: str) -> Path:
        directory = self.root / collection
        if not (directory / "schema.json").is_file():
            raise CollectionNotFound(collection)
        return directory

    def _item_path(self, collection: str, item_id: str) -> Path:
        return self._collection_dir(collection) / "items" / f"{item_id}.json"

    def _load_all(self, collection: str) -> list[Item]:
        items_dir = self._collection_dir(collection) / "items"
        if not items_dir.is_dir():
            return []
        items: list[Item] = []
        for file in sorted(items_dir.glob("*.json")):
            data = json.loads(file.read_text(encoding="utf-8"))
            items.append(Item(id=file.stem, data=data))
        return items

    # -- reads -----------------------------------------------------------
    def list_collections(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.name
            for p in self.root.iterdir()
            if p.is_dir() and (p / "schema.json").is_file()
        )

    def get_schema(self, collection: str) -> dict[str, Any]:
        directory = self._collection_dir(collection)
        return json.loads((directory / "schema.json").read_text(encoding="utf-8"))

    def list_items(self, collection: str, query: Query) -> Page[Item]:
        items = self._filter(self._load_all(collection), query)
        total = len(items)
        items = self._sort(items, query)
        window = items[query.offset : query.offset + query.limit]
        return Page[Item](items=window, total=total, limit=query.limit, offset=query.offset)

    def get_item(self, collection: str, item_id: str) -> Item:
        path = self._item_path(collection, item_id)
        if not path.is_file():
            raise ItemNotFound(collection, item_id)
        return Item(id=item_id, data=json.loads(path.read_text(encoding="utf-8")))

    # -- writes ----------------------------------------------------------
    def create_item(self, collection: str, data: dict[str, Any]) -> Item:
        self._collection_dir(collection)  # ensure the collection exists
        # The filename is the single source of truth for the id; a provided
        # ``id`` is used only to name the file and is not stored in the data,
        # so items are consistent however they were created.
        data = dict(data)
        provided_id = data.pop("id", None)
        item_id = str(provided_id) if provided_id else uuid.uuid4().hex
        path = self._item_path(collection, item_id)
        if path.exists():
            raise Conflict(f"Item already exists: {collection!r}/{item_id!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, data)
        return Item(id=item_id, data=data)

    def update_item(self, collection: str, item_id: str, patch: dict[str, Any]) -> Item:
        path = self._item_path(collection, item_id)
        if not path.is_file():
            raise ItemNotFound(collection, item_id)
        merged = {**json.loads(path.read_text(encoding="utf-8")), **patch}
        self._write(path, merged)
        return Item(id=item_id, data=merged)

    def delete_item(self, collection: str, item_id: str) -> None:
        path = self._item_path(collection, item_id)
        if not path.is_file():
            raise ItemNotFound(collection, item_id)
        path.unlink()

    # -- in-memory query engine -----------------------------------------
    @staticmethod
    def _filter(items: list[Item], query: Query) -> list[Item]:
        result = items
        if query.filters:
            result = [
                item
                for item in result
                if all(str(item.data.get(k)) == v for k, v in query.filters.items())
            ]
        if query.q:
            needle = query.q.lower()
            result = [item for item in result if _contains(item.data, needle)]
        return result

    @staticmethod
    def _sort(items: list[Item], query: Query) -> list[Item]:
        if not query.sort:
            return items
        field = query.sort
        # (value is None, value) keeps missing values grouped together so that
        # None is never compared against a typed value.
        return sorted(
            items,
            key=lambda item: (item.data.get(field) is None, item.data.get(field)),
            reverse=query.order == "desc",
        )

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _contains(data: dict[str, Any], needle: str) -> bool:
    """True if any string value (top-level or nested in lists) contains needle."""
    for value in data.values():
        if isinstance(value, str) and needle in value.lower():
            return True
        if isinstance(value, list) and any(
            isinstance(v, str) and needle in v.lower() for v in value
        ):
            return True
    return False
