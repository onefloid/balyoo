"""Static site export: the JSON mirror matches the service, and assets ship."""

from __future__ import annotations

import json
from pathlib import Path

from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_schema.validator import JsonSchemaValidator
from collections_static.exporter import export_site


def _export(root: Path, out: Path) -> None:
    service = CollectionsService(
        FilesystemStorageProvider(root), JsonSchemaValidator(), read_only=True
    )
    export_site(service, out)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_collections_index_matches_service(examples_copy, tmp_path):
    out = tmp_path / "dist"
    _export(examples_copy, out)

    index = _load(out / "api" / "collections.json")
    assert {c["name"] for c in index} == {"books", "movies"}
    # Exported read-only: capabilities must advertise no writes.
    assert all(c["capabilities"]["supports_write"] is False for c in index)


def test_schema_and_items_mirror(examples_copy, tmp_path):
    out = tmp_path / "dist"
    _export(examples_copy, out)
    api = out / "api" / "collections"

    assert _load(api / "books" / "schema.json")["title"] == "Book"

    items = _load(api / "books" / "items.json")
    assert items["total"] == 2
    assert {i["id"] for i in items["items"]} == {"dune", "lotr"}

    dune = _load(api / "books" / "items" / "dune.json")
    assert dune["id"] == "dune"
    assert dune["data"]["title"] == "Dune"


def test_ui_assets_are_written(examples_copy, tmp_path):
    out = tmp_path / "dist"
    _export(examples_copy, out)
    for name in ("index.html", "app.js", "style.css"):
        assert (out / name).is_file(), name
    assert "api/" in (out / "app.js").read_text(encoding="utf-8")
