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
from collections_static.exporter import export_site
from cyclopts import App

from collections_cli.ingest import plan_upsert, resolve_slug

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
    ui: Path | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Serve the generic REST API (add --read-only to mask writes).

    Pass --ui <dir> with a built collections-ui bundle to also serve the web UI
    from the same origin (no separate host, no CORS).
    """
    import uvicorn
    from collections_rest.app import create_app

    service = _service(root, read_only=read_only)
    uvicorn.run(create_app(service, ui_dir=ui), host=host, port=port)


@app.command
def mcp(*, read_only: bool = False, root: Path = DEFAULT_ROOT) -> None:
    """Serve collections over the Model Context Protocol (stdio).

    Point an MCP host (e.g. Claude Desktop) at this command to let an assistant
    read and write collections as tools. Add --read-only to expose read tools only.
    """
    from collections_mcp.server import run_stdio

    service = _service(root, read_only=read_only)
    run_stdio(service)


@app.command
def export(*, out: Path = Path("dist"), root: Path = DEFAULT_ROOT) -> None:
    """Export a static, read-only site (JSON API mirror + minimal UI) to a directory."""
    service = _service(root, read_only=True)
    export_site(service, out)
    print(f"exported static site to {out}")


@app.command
def ingest(
    collection: str,
    *,
    data: str,
    id: str | None = None,
    yes: bool = False,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Create or update an item from JSON, validated against the schema.

    Decides create vs. update by id, validates the result, prints a preview
    (a field diff for updates), and asks for confirmation unless --yes is given.
    Does not commit or push; publishing is a separate, explicit step.
    """
    service = _service(root, read_only=False)
    payload = json.loads(data)
    slug = resolve_slug(payload, id)
    plan = plan_upsert(service, collection, slug, payload)

    print(f"{plan.action} {collection}/{slug}")
    if plan.action == "update":
        if plan.changes:
            print("changes:")
            for line in plan.changes:
                print(f"  {line}")
        else:
            print("  (no changes)")
    else:
        print(json.dumps(plan.target, indent=2, ensure_ascii=False))

    if not yes and not _confirm():
        print("aborted", file=sys.stderr)
        raise SystemExit(1)

    if plan.action == "create":
        service.create_item(collection, {**payload, "id": slug})
    else:
        service.update_item(collection, slug, {k: v for k, v in payload.items() if k != "id"})
    print(f"{plan.action}d {collection}/{slug}")


def _confirm() -> bool:
    try:
        return input("Publish this? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main() -> None:
    try:
        app()
    except CollectionsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
