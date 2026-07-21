"""The chat feature's ASGI app: a single SSE endpoint at ``/stream``.

Mounted at ``/chat`` by ``collections_mcp.http.build_asgi_app`` (see
``chat_app`` there), parallel to how that module already optionally mounts the
REST API at ``/collections``. This module never imports from
``collections_mcp.http``'s MCP/OAuth internals -- it only depends on
``collections_core`` and its own ``agent``/``auth``/``quota`` modules, so
adding it cannot regress the existing MCP transport.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from collections_chat.agent import run_turn
from collections_chat.auth import ChatAuthenticator
from collections_chat.quota import QuotaExceeded, QuotaStore
from collections_core.service import CollectionsService
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp

logger = logging.getLogger("collections_chat")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_chat_asgi_app(
    service: CollectionsService,
    client: Any,  # anthropic.AsyncAnthropic
    model: str,
    authenticator: ChatAuthenticator,
    quota: QuotaStore,
) -> ASGIApp:
    """Build the chat app. ``service`` must be write-capable -- the whole point
    of this feature is letting the owner create/edit items by chatting."""

    async def chat_stream(request: Request) -> StreamingResponse | JSONResponse:
        actor = authenticator.authenticate(request)
        if actor is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        body_bytes = await request.body()
        try:
            quota.check_body_size(len(body_bytes))
            quota.check_and_consume_request(actor.id)
            quota.check_token_budget()
        except QuotaExceeded as exc:
            return JSONResponse({"error": str(exc)}, status_code=429)

        try:
            body = json.loads(body_bytes)
            message = body["message"]
            history = body.get("history", [])
            active_collections = set(body.get("active_collections", []))
        except (json.JSONDecodeError, KeyError, TypeError):
            return JSONResponse({"error": "invalid request body"}, status_code=400)

        async def event_stream() -> AsyncIterator[str]:
            total_tokens = 0
            try:
                async for event in run_turn(
                    service,
                    client,
                    model,
                    history,
                    message,
                    active_collections=active_collections,
                ):
                    payload = dataclasses.asdict(event)
                    event_type = payload.pop("type")
                    if event_type in ("done", "error"):
                        total_tokens = payload.get("input_tokens", 0) + payload.get(
                            "output_tokens", 0
                        )
                    yield _sse(event_type, payload)
            except Exception:
                logger.exception("chat: unhandled error in event stream")
                yield _sse("error", {"message": "internal error"})
            finally:
                if total_tokens:
                    quota.record_usage(total_tokens)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/stream", chat_stream, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ]
    )
