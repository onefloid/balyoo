"""The chat agent loop: an Anthropic tool-use loop over ``dispatch()``.

Reuses ``collections_mcp.server.build_tools``/``dispatch`` directly -- both are
already transport-agnostic, so this talks to them as plain Python calls rather
than speaking the MCP wire protocol. The one thing added on top is dynamic tool
filtering: ``build_tools`` puts every collection's full JSON Schema into that
collection's ``create_<c>``/``update_<c>`` tool, and sending all of them on
every call scales cost with total collection count regardless of caching. This
module keeps the tool list to the generic tools plus only the collections a
given conversation has actually touched.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from collections_core.errors import CollectionsError, SchemaValidationError
from collections_core.service import CollectionsService
from collections_mcp.server import build_tools, dispatch

logger = logging.getLogger("collections_chat")

# Mirrors the prefix convention build_tools() uses for per-collection tools
# (collections_mcp.server._CREATE/_UPDATE); kept local rather than importing
# those private names across a package boundary.
_CREATE = "create_"
_UPDATE = "update_"

MAX_TOOL_ITERATIONS = 8
MAX_ACTIVE_COLLECTIONS = 3
MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are the in-app assistant for a Balyoo Collections site. You help the \
operator create and edit items in their collections by chatting, using the \
tools available to you.

- Discover collections with `list_collections`/`get_schema` before creating or \
editing items in one you haven't used yet in this conversation.
- Confirm the collection and the data you're about to write in a short summary \
before calling a create/update/delete tool, unless the user has already been \
explicit about both.
- After a successful write, briefly say what changed (collection + item id).
- If a tool call fails, explain the error in plain language and, for schema \
validation errors, tell the user exactly which fields are wrong.
"""


# -- events streamed to the client ----------------------------------------
@dataclass(frozen=True)
class TokenEvent:
    text: str
    type: Literal["token"] = "token"


@dataclass(frozen=True)
class ToolCallEvent:
    name: str
    arguments: dict[str, Any]
    type: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class ToolResultEvent:
    name: str
    result: Any
    is_error: bool
    type: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class DoneEvent:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    type: Literal["done"] = "done"


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    input_tokens: int = 0
    output_tokens: int = 0
    type: Literal["error"] = "error"


ChatEvent = TokenEvent | ToolCallEvent | ToolResultEvent | DoneEvent | ErrorEvent


# -- tool selection ----------------------------------------------------------
def _is_typed_write_tool(name: str) -> str | None:
    """Return the collection name if ``name`` is a per-collection create/update
    tool, else ``None``."""
    if name.startswith(_CREATE) and name != "create_collection":
        return name[len(_CREATE) :]
    if name.startswith(_UPDATE) and name != "update_schema":
        return name[len(_UPDATE) :]
    return None


def active_tools(
    service: CollectionsService, active_collections: set[str]
) -> list[dict[str, Any]]:
    """The Anthropic-shaped tool list: generic tools always, typed create/update
    tools only for ``active_collections``."""
    tools = []
    for tool in build_tools(service):
        collection = _is_typed_write_tool(tool.name)
        if collection is not None and collection not in active_collections:
            continue
        tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
        )
    return tools


def _cached_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the last tool with an ephemeral cache breakpoint.

    Anthropic caches everything up to and including a marked block, so placing
    the breakpoint on the last tool caches the whole tools array as one unit.
    Cheap and correct even though it doesn't split generic vs. per-collection
    tools into separate breakpoints (see module docstring / plan for why that
    refinement is a later optimisation, not required for correctness).
    """
    if not tools:
        return tools
    tools = [dict(t) for t in tools]
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools


def _format_tool_error(exc: CollectionsError) -> str:
    message = str(exc)
    if isinstance(exc, SchemaValidationError):
        message += "\n- " + "\n- ".join(exc.errors)
    return message


# -- the loop ------------------------------------------------------------
async def run_turn(
    service: CollectionsService,
    client: Any,  # anthropic.AsyncAnthropic
    model: str,
    history: list[dict[str, Any]],
    user_message: str,
    *,
    active_collections: set[str] | None = None,
) -> AsyncIterator[ChatEvent]:
    """Run one user turn to completion, streaming events as they happen.

    ``history`` is the prior turns in Anthropic message format (as sent back by
    the client -- this loop is stateless server-side). ``active_collections``
    seeds which collections' typed tools are already available (e.g. the
    collection the chat was opened from); it grows as the model calls
    ``get_schema``/``list_items`` on collections it hasn't used yet.
    """
    active = set(active_collections or ())
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_message}]
    total_input_tokens = 0
    total_output_tokens = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        tools = _cached_tools(active_tools(service, active))
        text_parts: list[str] = []
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=tools,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    text_parts.append(text)
                    yield TokenEvent(text)
                response = await stream.get_final_message()
        except Exception as exc:  # network/API failure, not a domain error
            logger.exception("chat: LLM call failed")
            yield ErrorEvent(
                f"LLM request failed: {exc}",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )
            return

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            yield DoneEvent(
                "".join(text_parts),
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )
            return

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            collection = _is_typed_write_tool(block.name)
            if collection is not None:
                active.add(collection)
                if len(active) > MAX_ACTIVE_COLLECTIONS:
                    # Keep the set bounded; drop an arbitrary older entry rather
                    # than growing the tool list unboundedly in a long, wide-
                    # ranging conversation.
                    active.pop()
                    active.add(collection)

            yield ToolCallEvent(block.name, block.input)
            try:
                result = dispatch(service, block.name, block.input)
                payload = json.dumps(result, ensure_ascii=False)
                is_error = False
            except CollectionsError as exc:
                logger.info("chat: tool %s failed: %s", block.name, type(exc).__name__)
                payload = _format_tool_error(exc)
                is_error = True
            except ValueError as exc:  # unknown tool name
                payload = str(exc)
                is_error = True

            yield ToolResultEvent(block.name, payload, is_error)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": payload,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    yield ErrorEvent(
        "Reached the tool-call limit for this turn; please try again.",
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )
