"""cyclopts-based CLI for the Collections platform."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from collections_core.errors import CollectionsError, Conflict
from collections_core.interfaces import StorageProvider
from collections_core.models import Query
from collections_core.service import CollectionsService
from collections_filesystem.provider import FilesystemStorageProvider
from collections_schema.validator import JsonSchemaValidator
from collections_sqlite.provider import SqliteStorageProvider
from collections_static.exporter import export_site
from cyclopts import App

from collections_cli.ingest import plan_upsert, resolve_slug

DEFAULT_ROOT = Path("examples/collections")

app = App(name="collections", help="Generic schema-driven collections platform.")
items_app = App(name="items", help="Manage items within a collection.")
app.command(items_app)


def _provider(root: Path, db: Path | None) -> StorageProvider:
    """Pick the storage backend: SQLite when ``--db`` is given, else the filesystem."""
    if db is not None:
        return SqliteStorageProvider(db)
    return FilesystemStorageProvider(root)


def _service(
    root: Path,
    *,
    read_only: bool,
    deletable: bool = True,
    db: Path | None = None,
) -> CollectionsService:
    return CollectionsService(
        _provider(root, db),
        JsonSchemaValidator(),
        read_only=read_only,
        deletable=deletable,
    )


@app.command(name="list")
def list_collections(*, db: Path | None = None, root: Path = DEFAULT_ROOT) -> None:
    """List all collections and their item counts."""
    service = _service(root, read_only=True, db=db)
    for info in service.list_collections():
        print(f"{info.name}\t({info.item_count} items)")


@app.command
def schema(collection: str, *, db: Path | None = None, root: Path = DEFAULT_ROOT) -> None:
    """Print the JSON Schema of a collection."""
    service = _service(root, read_only=True, db=db)
    print(json.dumps(service.get_schema(collection), indent=2, ensure_ascii=False))


@items_app.command(name="list")
def items_list(
    collection: str,
    *,
    q: str | None = None,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Path | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    """List (and optionally search) items in a collection."""
    service = _service(root, read_only=True, db=db)
    page = service.list_items(
        collection, Query(q=q, sort=sort, limit=limit, offset=offset)
    )
    for item in page.items:
        print(f"{item.id}\t{json.dumps(item.data, ensure_ascii=False)}")
    print(f"# {page.total} total", file=sys.stderr)


@items_app.command(name="get")
def items_get(
    collection: str, item_id: str, *, db: Path | None = None, root: Path = DEFAULT_ROOT
) -> None:
    """Print a single item's data."""
    service = _service(root, read_only=True, db=db)
    print(json.dumps(service.get_item(collection, item_id).data, indent=2, ensure_ascii=False))


@items_app.command(name="create")
def items_create(
    collection: str, *, data: str, db: Path | None = None, root: Path = DEFAULT_ROOT
) -> None:
    """Create an item from a JSON string (validated against the schema)."""
    service = _service(root, read_only=False, db=db)
    item = service.create_item(collection, json.loads(data))
    print(item.id)


@items_app.command(name="update")
def items_update(
    collection: str,
    item_id: str,
    *,
    data: str,
    db: Path | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Merge a JSON patch into an existing item (validated against the schema)."""
    service = _service(root, read_only=False, db=db)
    item = service.update_item(collection, item_id, json.loads(data))
    print(json.dumps(item.data, indent=2, ensure_ascii=False))


@items_app.command(name="delete")
def items_delete(
    collection: str, item_id: str, *, db: Path | None = None, root: Path = DEFAULT_ROOT
) -> None:
    """Delete an item."""
    service = _service(root, read_only=False, db=db)
    service.delete_item(collection, item_id)
    print(f"deleted {collection}/{item_id}")


@app.command
def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    read_only: bool = False,
    ui: Path | None = None,
    db: Path | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Serve the generic REST API (add --read-only to mask writes).

    Pass --ui <dir> with a built collections-ui bundle to also serve the web UI
    from the same origin (no separate host, no CORS). Pass --db <path> to use the
    durable SQLite backend instead of the filesystem root.
    """
    import uvicorn
    from collections_rest.app import create_app

    service = _service(root, read_only=read_only, db=db)
    uvicorn.run(create_app(service, ui_dir=ui), host=host, port=port)


@app.command
def mcp(
    *,
    http: bool = False,
    host: str = "127.0.0.1",
    port: int = 8080,
    read_only: bool = False,
    no_delete: bool = False,
    allow_anonymous: bool = False,
    rest: bool = False,
    db: Path | None = None,
    root: Path = DEFAULT_ROOT,
) -> None:
    """Serve collections over the Model Context Protocol.

    Default transport is stdio (what a local host like Claude Desktop launches).
    Add --http to serve the remote Streamable HTTP transport for a cloud LLM,
    protected by a static bearer token: set COLLECTIONS_MCP_TOKEN and every request
    to /mcp must send `Authorization: Bearer <token>`. Capabilities come from flags,
    not the token: --read-only serves read tools only, --no-delete hides delete_item.
    Pass --allow-anonymous to serve without a token (no authentication). Pass --db
    <path> to use the durable SQLite backend instead of the filesystem root.

    Add --rest (only with --http) to additionally serve the generic REST API under
    /collections in the same process and against the same backend. It is served
    read-only and without the /mcp bearer token — a public, browser-readable mirror
    of the data (CORS is open) — so no separate container or volume is needed.

    Hosts that require a real OAuth flow (ChatGPT, Claude.ai custom connectors)
    can't use a bare bearer token. Setting all four of COLLECTIONS_MCP_OAUTH_CLIENT_ID,
    COLLECTIONS_MCP_OAUTH_CLIENT_SECRET, COLLECTIONS_MCP_OAUTH_REDIRECT_URIS
    (comma-separated) and COLLECTIONS_MCP_PUBLIC_URL (this server's own https://
    base URL) makes this server additionally act as its own OAuth 2.1 Authorization
    Server for that one pre-registered client; /mcp then accepts either the static
    token or a token issued through that flow. See packages/collections-mcp/README.md.
    """
    if rest and not http:
        print("error: --rest only applies with --http", file=sys.stderr)
        raise SystemExit(2)

    if not http:
        from collections_mcp.server import run_stdio

        run_stdio(_service(root, read_only=read_only, db=db))
        return

    import os

    import uvicorn
    from collections_mcp.http import OAuthConfig, build_asgi_app

    token = os.environ.get("COLLECTIONS_MCP_TOKEN")
    if token is None and not allow_anonymous:
        print(
            "error: --http requires COLLECTIONS_MCP_TOKEN "
            "(or pass --allow-anonymous to serve without authentication)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    oauth = None
    if not allow_anonymous:
        oauth_client_id = os.environ.get("COLLECTIONS_MCP_OAUTH_CLIENT_ID")
        oauth_client_secret = os.environ.get("COLLECTIONS_MCP_OAUTH_CLIENT_SECRET")
        oauth_redirect_uris = os.environ.get("COLLECTIONS_MCP_OAUTH_REDIRECT_URIS")
        oauth_public_url = os.environ.get("COLLECTIONS_MCP_PUBLIC_URL")
        configured = [oauth_client_id, oauth_client_secret, oauth_redirect_uris, oauth_public_url]
        if any(configured) and not all(configured):
            print(
                "error: COLLECTIONS_MCP_OAUTH_CLIENT_ID, COLLECTIONS_MCP_OAUTH_CLIENT_SECRET, "
                "COLLECTIONS_MCP_OAUTH_REDIRECT_URIS and COLLECTIONS_MCP_PUBLIC_URL "
                "must all be set together to enable OAuth",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if all(configured):
            redirect_uris = [uri.strip() for uri in oauth_redirect_uris.split(",") if uri.strip()]
            oauth = OAuthConfig(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                redirect_uris=redirect_uris,
                public_url=oauth_public_url,
            )

    service = _service(root, read_only=read_only, deletable=not no_delete, db=db)
    rest_service = _service(root, read_only=True, db=db) if rest else None
    uvicorn.run(
        build_asgi_app(service, token=token, oauth=oauth, rest_service=rest_service),
        host=host,
        port=port,
    )


@app.command
def migrate(*, db: Path, root: Path = DEFAULT_ROOT) -> None:
    """Import collections and items from a filesystem <root> into a SQLite <db>.

    Idempotent: re-running skips items that already exist, so it can seed a fresh
    database or top up an existing one.
    """
    source = _service(root, read_only=True)
    target = SqliteStorageProvider(db)
    collections = imported = 0
    for info in source.list_collections():
        target.create_collection(info.name, source.get_schema(info.name))
        collections += 1
        offset = 0
        while True:
            page = source.list_items(info.name, Query(limit=1000, offset=offset))
            for item in page.items:
                try:
                    target.create_item(info.name, {**item.data, "id": item.id})
                    imported += 1
                except Conflict:
                    pass  # already present
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
    print(f"migrated {collections} collections, {imported} items into {db}")


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
