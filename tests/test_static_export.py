"""Static site export: the JSON mirror matches the service, and config ships."""

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


def test_ui_config_is_written(examples_copy, tmp_path):
    out = tmp_path / "dist"
    _export(examples_copy, out)

    config = _load(out / "config.json")
    # The UI reads this to target the mirror in read-only static mode.
    assert config == {"apiBase": "api/", "static": True}


def test_live_url_writes_dual_mode_config(examples_copy, tmp_path):
    out = tmp_path / "dist"
    service = CollectionsService(
        FilesystemStorageProvider(examples_copy), JsonSchemaValidator(), read_only=True
    )
    export_site(service, out, live_url="https://balyoo.fly.dev/")

    # Dual mode: default to the live server, keep the exported mirror as fallback.
    assert _load(out / "config.json") == {
        "apiBase": "https://balyoo.fly.dev/",
        "static": False,
        "staticBase": "api/",
    }
    # The mirror is still exported so the fallback has data to serve.
    assert (out / "api" / "collections.json").is_file()


def test_live_url_with_chat_url_adds_chat_base(examples_copy, tmp_path):
    out = tmp_path / "dist"
    service = CollectionsService(
        FilesystemStorageProvider(examples_copy), JsonSchemaValidator(), read_only=True
    )
    export_site(
        service, out, live_url="https://balyoo.fly.dev/", chat_url="https://balyoo.fly.dev/chat"
    )

    assert _load(out / "config.json") == {
        "apiBase": "https://balyoo.fly.dev/",
        "static": False,
        "staticBase": "api/",
        "chatBase": "https://balyoo.fly.dev/chat",
    }


def test_chat_url_without_live_url_is_ignored(examples_copy, tmp_path):
    # chat_url only makes sense alongside a live server; without live_url the
    # config falls back to the plain read-only static mode, same as if chat_url
    # had never been passed (guard against silently mixing modes).
    out = tmp_path / "dist"
    service = CollectionsService(
        FilesystemStorageProvider(examples_copy), JsonSchemaValidator(), read_only=True
    )
    export_site(service, out, chat_url="https://balyoo.fly.dev/chat")

    assert _load(out / "config.json") == {"apiBase": "api/", "static": True}


def test_export_leaves_existing_ui_files_untouched(examples_copy, tmp_path):
    # The Pages workflow lays the built collections-ui bundle into the output dir
    # first; the export must only add api/** and config.json, never clobber it.
    out = tmp_path / "dist"
    out.mkdir()
    (out / "index.html").write_text("<!-- built UI -->", encoding="utf-8")
    (out / "assets").mkdir()
    (out / "assets" / "app.js").write_text("console.log('ui')", encoding="utf-8")

    _export(examples_copy, out)

    assert (out / "index.html").read_text(encoding="utf-8") == "<!-- built UI -->"
    assert (out / "assets" / "app.js").is_file()
    assert (out / "api" / "collections.json").is_file()
