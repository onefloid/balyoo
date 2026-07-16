"""cyclopts-based CLI for the Collections platform."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from collections_core.errors import CollectionsError
from collections_core.models import Query
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_schema.validator import JsonSchemaValidator
from cyclopts import App

DEFAULT_ROOT = Path("examples/collections")

app = App(name="collections", help="Generic schema-driven collections platform.")
items_app = App(name="items", help="Manage items within a collection.")
app.command(items_app)


def _service(root: Path, *, read_only: bool) -> CollectionsService:
    provider = FilesystemStorageProvider(root)
    return CollectionsService(provider, JsonSchemaValidator(), read_only=read_only)


@app.command(name="list")
def list_collections(*, root: Path = DEFAULT_ROOT) -> None:
    """List all collections and their item counts."""
    service = _service(root, read_only=True)
    for info in service.list_collections():
        print(f"{info.name}\t({info.item_count} items)")


@app.command
def schema(collection: str, *, root: Path = DEFAULT_ROOT) -> None:
    """Print the JSON Schema of a collection."""
    service = _service(root, read_only=True)
    print(json.dumps(service.get_schema(collection), indent=2, ensure_ascii=False))


@items_app.command(name="list")
def items_list(
    collection: str,
    *,
    q: str | None = None,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
    root: Path = DEFAULT_ROOT,
) -> None:
    """List (and optionally search) items in a collection."""
    service = _service(root, read_only=True)
    page = service.list_items(
        collection, Query(q=q, sort=sort, limit=limit, offset=offset)
    )
    for item in page.items:
        print(f"{item.id}\t{json.dumps(item.data, ensure_ascii=False)}")
    print(f"# {page.total} total", file=sys.stderr)


@items_app.command(name="get")
def items_get(collection: str, item_id: str, *, root: Path = DEFAULT_ROOT) -> None:
    """Print a single item's data."""
    service = _service(root, read_only=True)
    print(json.dumps(service.get_item(collection, item_id).data, indent=2, ensure_ascii=False))


@items_app.command(name="create")
def items_create(collection: str, *, data: str, root: Path = DEFAULT_ROOT) -> None:
    """Create an item from a JSON string (validated against the schema)."""
    service = _service(root, read_only=False)
    item = service.create_item(collection, json.loads(data))
    print(item.id)


@items_app.command(name="update")
def items_update(
    collection: str, item_id: str, *, data: str, root: Path = DEFAULT_ROOT
) -> None:
    """Merge a JSON patch into an existing item (validated against the schema)."""
    service = _service(root, read_only=False)
    item = service.update_item(collection, item_id, json.loads(data))
    print(json.dumps(item.data, indent=2, ensure_ascii=False))


@items_app.command(name="delete")
def items_delete(collection: str, item_id: str, *, root: Path = DEFAULT_ROOT) -> None:
    """Delete an item."""
    service = _service(root, read_only=False)
    service.delete_item(collection, item_id)
    print(f"deleted {collection}/{item_id}")


@app.command
def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    read_only: bool = False,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Serve the generic REST API (add --read-only to mask writes)."""
    import uvicorn
    from collections_rest.app import create_app

    service = _service(root, read_only=read_only)
    uvicorn.run(create_app(service), host=host, port=port)


def main() -> None:
    try:
        app()
    except CollectionsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
