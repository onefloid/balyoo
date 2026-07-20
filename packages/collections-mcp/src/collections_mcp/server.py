"""MCP server built on a :class:`CollectionsService`.

The tool set is generated from the platform itself: generic read tools plus, for
each collection, ``create_<collection>`` / ``update_<collection>`` whose input
schema is the collection's own JSON Schema — so an assistant gets typed, validated
write tools rather than an opaque "pass some JSON" call. Collection management
tools (``create_collection``, ``update_schema``, ``delete_collection``) let an
assistant define new collections and their schemas; a newly created collection's
typed write tools then appear automatically. Writes are advertised only when the
service's capabilities allow them (a ``--read-only`` server is read-only to the
assistant too).

The tool logic lives in the transport-agnostic :func:`build_tools` /
:func:`dispatch` so it can be unit-tested without a live MCP client; the stdio
server is a thin wrapper over them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import mcp.types as types
from collections_core.errors import CollectionsError, SchemaValidationError
from collections_core.models import Query
from collections_core.service import CollectionsService
from mcp.server.lowlevel import Server

logger = logging.getLogger("collections_mcp")

# Presentation-only keywords that must not leak into a write tool's input schema.
_SCHEMA_META = ("$schema", "x-card", "x-collection")

_CREATE = "create_"
_UPDATE = "update_"

# Collection-management tool names. Exact matches, checked before the ``create_``/
# ``update_`` prefix routing so they never collide with the per-collection tools.
_CREATE_COLLECTION = "create_collection"
_UPDATE_SCHEMA = "update_schema"
_DELETE_COLLECTION = "delete_collection"

# Doubles as the assistant's guidance for authoring a schema.
_CREATE_COLLECTION_DESCRIPTION = """\
Create a new collection from a JSON Schema. Use this to help a user model \
whatever they want to collect, then define it here.

`schema` is a JSON Schema (draft 2020-12) describing one item:
- `type` must be `object`; put the item's fields under `properties`.
- `required` lists the fields that must always be present.
- Field types: `string`, `integer`, `number`, `boolean`, `array` (with `items`), \
`object`. Add constraints like `minimum`, `enum`, or `format` where useful.
- Optional presentation keys the UI understands:
  - `x-collection`: `{ "icon": "📚", "color": "#8b5cf6" }` (emoji icon + accent).
  - `x-card`: how to render an item card, e.g. \
`{ "default": "cards", "title": "<field>", "subtitle": "<field>", \
"badges": ["<field>"], "fields": ["<field>"] }`.

Example `schema` for a "books" collection:
{
  "type": "object",
  "properties": {
    "title": { "type": "string" },
    "author": { "type": "string" },
    "year": { "type": "integer" },
    "tags": { "type": "array", "items": { "type": "string" } }
  },
  "required": ["title"],
  "x-collection": { "icon": "📚" },
  "x-card": { "default": "cards", "title": "title", "subtitle": "author", \
"badges": ["tags"], "fields": ["year"] }
}

Once created, typed `create_<name>` / `update_<name>` tools for the new \
collection appear automatically. The schema is stored as a versioned file; \
publishing changes to a live site still goes through the normal git flow.\
"""


# -- tool definitions ----------------------------------------------------------
def _write_schema(schema: dict[str, Any], *, for_update: bool) -> dict[str, Any]:
    """A collection's JSON Schema, adapted for a create/update tool's input."""
    cleaned = {k: v for k, v in schema.items() if k not in _SCHEMA_META}
    cleaned.setdefault("type", "object")
    if not for_update:
        return cleaned
    # Update takes an item id plus a partial patch: id is the only required field,
    # and any subset of properties may be supplied.
    props = {"id": {"type": "string", "description": "Id of the item to update."}}
    props.update(cleaned.get("properties", {}))
    patch = {**cleaned, "properties": props, "required": ["id"]}
    patch.pop("additionalProperties", None)
    return patch


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def build_tools(service: CollectionsService) -> list[types.Tool]:
    """The tools this service exposes, gated by its effective capabilities."""
    caps = service.capabilities
    tools: list[types.Tool] = [
        types.Tool(
            name="list_collections",
            description="List all collections with their capabilities and item counts.",
            inputSchema=_obj({}, []),
        ),
        types.Tool(
            name="get_schema",
            description="Get the JSON Schema of a collection.",
            inputSchema=_obj({"collection": {"type": "string"}}, ["collection"]),
        ),
        types.Tool(
            name="list_items",
            description=(
                "List or search items in a collection. `q` is a full-text query; "
                "results can be sorted and paginated."
            ),
            inputSchema=_obj(
                {
                    "collection": {"type": "string"},
                    "q": {"type": "string", "description": "Full-text search query."},
                    "sort": {"type": "string", "description": "Field to sort by."},
                    "order": {"type": "string", "enum": ["asc", "desc"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    "offset": {"type": "integer", "minimum": 0},
                },
                ["collection"],
            ),
        ),
        types.Tool(
            name="get_item",
            description="Get a single item by id.",
            inputSchema=_obj(
                {"collection": {"type": "string"}, "id": {"type": "string"}},
                ["collection", "id"],
            ),
        ),
    ]

    if caps.supports_write:
        tools.append(
            types.Tool(
                name=_CREATE_COLLECTION,
                description=_CREATE_COLLECTION_DESCRIPTION,
                inputSchema=_obj(
                    {
                        "name": {
                            "type": "string",
                            "description": "Collection name (a single path segment).",
                        },
                        "schema": {
                            "type": "object",
                            "description": "The collection's JSON Schema (draft 2020-12).",
                        },
                    },
                    ["name", "schema"],
                ),
            )
        )
        tools.append(
            types.Tool(
                name=_UPDATE_SCHEMA,
                description=(
                    "Replace a collection's JSON Schema. Same schema format as "
                    "create_collection. Returns the ids of any existing items that "
                    "no longer conform to the new schema (a non-blocking warning)."
                ),
                inputSchema=_obj(
                    {
                        "collection": {"type": "string"},
                        "schema": {
                            "type": "object",
                            "description": "The new JSON Schema (draft 2020-12).",
                        },
                    },
                    ["collection", "schema"],
                ),
            )
        )
        for info in service.list_collections():
            schema = service.get_schema(info.name)
            tools.append(
                types.Tool(
                    name=f"{_CREATE}{info.name}",
                    description=f"Create an item in the '{info.name}' collection.",
                    inputSchema=_write_schema(schema, for_update=False),
                )
            )
            tools.append(
                types.Tool(
                    name=f"{_UPDATE}{info.name}",
                    description=(
                        f"Update an item in '{info.name}' by id (partial patch; "
                        "only the given fields change)."
                    ),
                    inputSchema=_write_schema(schema, for_update=True),
                )
            )

    if caps.supports_delete:
        tools.append(
            types.Tool(
                name="delete_item",
                description="Delete an item by id.",
                inputSchema=_obj(
                    {"collection": {"type": "string"}, "id": {"type": "string"}},
                    ["collection", "id"],
                ),
            )
        )
        tools.append(
            types.Tool(
                name=_DELETE_COLLECTION,
                description=(
                    "Delete an entire collection, including its schema and all of "
                    "its items. This cannot be undone."
                ),
                inputSchema=_obj({"collection": {"type": "string"}}, ["collection"]),
            )
        )

    return tools


# -- tool execution ------------------------------------------------------------
def dispatch(service: CollectionsService, name: str, arguments: dict[str, Any]) -> Any:
    """Execute a tool call and return a JSON-serialisable payload.

    Raises :class:`CollectionsError` for domain failures (mapped to a tool error by
    the server) and ``ValueError`` for an unknown tool.
    """
    args = arguments or {}

    if name == "list_collections":
        return [info.model_dump() for info in service.list_collections()]
    if name == "get_schema":
        return service.get_schema(args["collection"])
    if name == "list_items":
        query = Query(
            q=args.get("q"),
            sort=args.get("sort"),
            order=args.get("order") or "asc",
            limit=args.get("limit", 50),
            offset=args.get("offset", 0),
        )
        return service.list_items(args["collection"], query).model_dump()
    if name == "get_item":
        return service.get_item(args["collection"], args["id"]).model_dump()
    if name == "delete_item":
        service.delete_item(args["collection"], args["id"])
        return {"deleted": f"{args['collection']}/{args['id']}"}
    # Collection management: exact-match before the create_/update_ prefix routing.
    if name == _CREATE_COLLECTION:
        service.create_collection(args["name"], args["schema"])
        return {"created": args["name"]}
    if name == _UPDATE_SCHEMA:
        invalid = service.update_schema(args["collection"], args["schema"])
        result: dict[str, Any] = {"updated": args["collection"]}
        if invalid:
            result["warning"] = (
                f"{len(invalid)} existing item(s) no longer conform to the new schema."
            )
            result["invalid_items"] = invalid
        return result
    if name == _DELETE_COLLECTION:
        service.delete_collection(args["collection"])
        return {"deleted_collection": args["collection"]}
    if name.startswith(_CREATE):
        collection = name[len(_CREATE) :]
        return service.create_item(collection, dict(args)).model_dump()
    if name.startswith(_UPDATE):
        collection = name[len(_UPDATE) :]
        data = dict(args)
        item_id = data.pop("id", None)
        if not item_id:
            raise ValueError("update requires an 'id'")
        return service.update_item(collection, str(item_id), data).model_dump()

    raise ValueError(f"Unknown tool: {name!r}")


# -- server --------------------------------------------------------------------
# A ServiceResolver produces the CollectionsService for the current call. For stdio
# it is a constant; for the HTTP server it inspects the authenticated request so a
# token's scopes decide read-only vs read-write (see ``http.py``).
ServiceResolver = Callable[[], CollectionsService]


def build_server(
    service: CollectionsService | ServiceResolver,
) -> Server:
    resolve: ServiceResolver = (
        service if callable(service) else (lambda svc=service: svc)
    )
    server: Server = Server("collections")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return build_tools(resolve())

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]):
        try:
            payload = dispatch(resolve(), name, arguments or {})
        except CollectionsError as exc:
            # Log the tool name and error type (no argument values, which may be
            # user content) so operators can debug connector issues.
            logger.info("tool %s failed: %s", name, type(exc).__name__)
            message = str(exc)
            if isinstance(exc, SchemaValidationError):
                message += "\n- " + "\n- ".join(exc.errors)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=message)],
                isError=True,
            )
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return [types.TextContent(type="text", text=text)]

    return server


def run_stdio(service: CollectionsService) -> None:
    """Serve the MCP server over stdio (the transport Claude Desktop launches)."""
    import anyio

    async def _serve() -> None:
        from mcp.server.stdio import stdio_server

        server = build_server(service)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    anyio.run(_serve)
