"""Filesystem-backed :class:`~collections_core.interfaces.StorageProvider`."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from collections_core.capabilities import Capabilities
from collections_core.errors import (
    CollectionExists,
    CollectionNotFound,
    Conflict,
    InvalidIdentifier,
    ItemNotFound,
)
from collections_core.models import Item, Page, Query
from collections_core.query import run_query


def _safe_segment(kind: str, value: str) -> str:
    """Return ``value`` if it is a single, safe path segment, else raise.

    Ids reach the provider from request bodies, URLs and the CLI, and are used to
    build filesystem paths. Rejecting empties, ``.``/``..`` and anything with a
    path separator (or NUL) keeps a caller from escaping the collection directory.
    """
    if (
        not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or "\0" in value
    ):
        raise InvalidIdentifier(kind, value)
    return value


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
        directory = self.root / _safe_segment("collection", collection)
        if not (directory / "schema.json").is_file():
            raise CollectionNotFound(collection)
        return directory

    def _item_path(self, collection: str, item_id: str) -> Path:
        segment = _safe_segment("item id", item_id)
        return self._collection_dir(collection) / "items" / f"{segment}.json"

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

    # -- collection management -------------------------------------------
    def create_collection(self, collection: str, schema: dict[str, Any]) -> None:
        """Create a new collection by writing its ``schema.json``.

        The schema is stored as a pretty-printed, git-diff-friendly JSON file --
        the same on-disk, versionable representation collections have always had,
        just written by a tool rather than by hand.
        """
        directory = self.root / _safe_segment("collection", collection)
        schema_path = directory / "schema.json"
        if schema_path.is_file():
            raise CollectionExists(collection)
        directory.mkdir(parents=True, exist_ok=True)
        self._write(schema_path, schema)

    def update_schema(self, collection: str, schema: dict[str, Any]) -> None:
        directory = self._collection_dir(collection)  # raises CollectionNotFound
        self._write(directory / "schema.json", schema)

    def delete_collection(self, collection: str) -> None:
        directory = self._collection_dir(collection)  # raises CollectionNotFound
        shutil.rmtree(directory)

    def list_items(self, collection: str, query: Query) -> Page[Item]:
        return run_query(self._load_all(collection), query)

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

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
