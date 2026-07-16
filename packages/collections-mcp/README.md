# collections-mcp (planned)

Auto-generated **MCP server** exposing every collection as tools
(`list_collections`, `list_items`, `search_items`, `get_item`, `create_item`,
`update_item`, `delete_item`). Tool descriptions and input schemas are generated
from each collection's JSON Schema — no hand-written MCP tools.

Will be built on top of `collections-core` (against `CollectionsService`), exactly
like `collections-rest`. Not implemented in milestone 1.
