"""Access control for the chat endpoint.

Balyoo has no multi-user auth anywhere yet (``collections-auth-basic`` is an
unimplemented placeholder), so the chat feature ships with the narrowest thing
that works today -- a single owner token -- behind an interface a real
multi-user authorizer can later satisfy without touching ``http.py`` or
``agent.py``.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from starlette.requests import Request


@dataclass(frozen=True)
class Actor:
    """The caller a chat request is attributed to.

    Deliberately the smallest shape a future real authorizer can also produce:
    an id for quota/audit attribution, and whether this actor may run the
    mutating tools at all.
    """

    id: str
    can_write: bool = True


class ChatAuthenticator(Protocol):
    def authenticate(self, request: Request) -> Actor | None:
        """Return the authenticated ``Actor``, or ``None`` to reject the request."""
        ...


class StaticOwnerAuthenticator:
    """Single-owner gate: one bearer token, checked in constant time.

    Same comparison used for ``COLLECTIONS_MCP_TOKEN`` in
    ``collections_mcp.http``, but this is a separate token/trust boundary --
    a browser session credential, not an MCP client credential -- so it is
    configured independently (``COLLECTIONS_CHAT_OWNER_TOKEN``).
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def authenticate(self, request: Request) -> Actor | None:
        header = request.headers.get("authorization", "")
        prefix = "bearer "
        provided = header[len(prefix) :] if header[: len(prefix)].lower() == prefix else ""
        if not provided and not self._token:
            return None
        if not hmac.compare_digest(provided, self._token):
            return None
        return Actor(id="owner", can_write=True)
