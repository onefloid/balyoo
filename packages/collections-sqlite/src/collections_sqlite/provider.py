"""SQLite-backed :class:`~collections_core.interfaces.StorageProvider`.

Collections and their JSON Schemas live in a ``collections`` table; each item is a
row in ``items`` (its ``data`` stored as JSON). Writes are atomic transactions.
Filtering, search, sorting and pagination reuse the shared in-memory engine
(:func:`collections_core.query.run_query`) so behaviour matches the filesystem
provider exactly.

A fresh connection is opened per operation, which keeps the provider safe to use
from the MCP HTTP server's worker threads without shared-connection hazards.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from collections_core.capabilities import Capabilities
from collections_core.errors import CollectionNotFound, Conflict, ItemNotFound
from collections_core.models import Item, Page, Query
from collections_core.query import run_query

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    name   TEXT PRIMARY KEY,
    schema TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    collection TEXT NOT NULL REFERENCES collections(name) ON DELETE CASCADE,
    id         TEXT NOT NULL,
    data       TEXT NOT NULL,
    PRIMARY KEY (collection, id)
);
"""


class SqliteStorageProvider:
    """Stores collections and items in a SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            supports_read=True,
            supports_write=True,
            supports_delete=True,
            supports_search=True,
            supports_transactions=True,
        )

    # -- collection management (beyond the read/write protocol) ----------
    def create_collection(self, name: str, schema: dict[str, Any]) -> None:
        """Register a collection and its JSON Schema (idempotent upsert)."""
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO collections(name, schema) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET schema = excluded.schema",
                (name, json.dumps(schema)),
            )
            conn.commit()

    # -- reads -----------------------------------------------------------
    def list_collections(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT name FROM collections ORDER BY name").fetchall()
        return [row[0] for row in rows]

    def get_schema(self, collection: str) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT schema FROM collections WHERE name = ?", (collection,)
            ).fetchone()
        if row is None:
            raise CollectionNotFound(collection)
        return json.loads(row[0])

    def list_items(self, collection: str, query: Query) -> Page[Item]:
        self.get_schema(collection)  # raises CollectionNotFound
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, data FROM items WHERE collection = ?", (collection,)
            ).fetchall()
        items = [Item(id=row[0], data=json.loads(row[1])) for row in rows]
        return run_query(items, query)

    def get_item(self, collection: str, item_id: str) -> Item:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM items WHERE collection = ? AND id = ?",
                (collection, item_id),
            ).fetchone()
        if row is None:
            raise ItemNotFound(collection, item_id)
        return Item(id=item_id, data=json.loads(row[0]))

    # -- writes ----------------------------------------------------------
    def create_item(self, collection: str, data: dict[str, Any]) -> Item:
        self.get_schema(collection)  # raises CollectionNotFound
        data = dict(data)
        provided_id = data.pop("id", None)
        item_id = str(provided_id) if provided_id else uuid.uuid4().hex
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                    "INSERT INTO items(collection, id, data) VALUES(?, ?, ?)",
                    (collection, item_id, json.dumps(data)),
                )
            except sqlite3.IntegrityError as exc:
                raise Conflict(
                    f"Item already exists: {collection!r}/{item_id!r}"
                ) from exc
            conn.commit()
        return Item(id=item_id, data=data)

    def update_item(self, collection: str, item_id: str, patch: dict[str, Any]) -> Item:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM items WHERE collection = ? AND id = ?",
                (collection, item_id),
            ).fetchone()
            if row is None:
                raise ItemNotFound(collection, item_id)
            merged = {**json.loads(row[0]), **patch}
            conn.execute(
                "UPDATE items SET data = ? WHERE collection = ? AND id = ?",
                (json.dumps(merged), collection, item_id),
            )
            conn.commit()
        return Item(id=item_id, data=merged)

    def delete_item(self, collection: str, item_id: str) -> None:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM items WHERE collection = ? AND id = ?",
                (collection, item_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise ItemNotFound(collection, item_id)
