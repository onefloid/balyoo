"""SQLite-backed rate limiting for the chat endpoint.

Chat is owner-only (see ``auth.py``), so this isn't primarily about stopping
strangers -- it's a sanity guard against an accidental runaway loop or a leaked
owner token. Counters must survive a process restart: the deployment scales to
zero (``min_machines_running = 0``), so an in-memory bucket would reset on
every cold start, which is exactly when a would-be abuser could probe for a
free reset. A dedicated SQLite file is used (not the collections DB) to avoid
any lock/WAL interplay with item CRUD on the same volume.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_quota (
    actor_id TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    window_seconds INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (actor_id, window_seconds, window_start)
);
CREATE TABLE IF NOT EXISTS chat_token_budget (
    day TEXT PRIMARY KEY,
    token_count INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class QuotaLimits:
    requests_per_minute: int = 5
    requests_per_day: int = 60
    daily_token_budget: int = 500_000
    max_body_bytes: int = 32_768


class QuotaExceeded(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class QuotaStore:
    """A tiny counter store; one instance per process, one SQLite file on disk."""

    def __init__(self, db_path: Path, limits: QuotaLimits | None = None) -> None:
        self._path = db_path
        self._limits = limits or QuotaLimits()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def limits(self) -> QuotaLimits:
        return self._limits

    def check_body_size(self, size: int) -> None:
        if size > self._limits.max_body_bytes:
            raise QuotaExceeded("Message too large.")

    def check_and_consume_request(self, actor_id: str, *, now: float | None = None) -> None:
        """Raise ``QuotaExceeded`` if ``actor_id`` is over the per-minute or
        per-day request limit; otherwise record this request."""
        now = time.time() if now is None else now
        minute_start = int(now // 60) * 60
        day_start = int(now // 86400) * 86400

        self._bump(actor_id, 60, minute_start)
        self._bump(actor_id, 86400, day_start)

        if self._count(actor_id, 60, minute_start) > self._limits.requests_per_minute:
            raise QuotaExceeded("Rate limit exceeded, try again in a minute.")
        if self._count(actor_id, 86400, day_start) > self._limits.requests_per_day:
            raise QuotaExceeded("Daily chat message limit reached, try again tomorrow.")

    def check_token_budget(self, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        row = self._conn.execute(
            "SELECT token_count FROM chat_token_budget WHERE day = ?", (day,)
        ).fetchone()
        used = row[0] if row else 0
        if used >= self._limits.daily_token_budget:
            raise QuotaExceeded("Chat is at capacity for today, please try again tomorrow.")

    def record_usage(self, total_tokens: int, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        self._conn.execute(
            """
            INSERT INTO chat_token_budget (day, token_count) VALUES (?, ?)
            ON CONFLICT(day) DO UPDATE SET token_count = token_count + excluded.token_count
            """,
            (day, total_tokens),
        )
        self._conn.commit()

    def _bump(self, actor_id: str, window_seconds: int, window_start: int) -> None:
        self._conn.execute(
            """
            INSERT INTO chat_quota (actor_id, window_start, window_seconds, request_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(actor_id, window_seconds, window_start)
            DO UPDATE SET request_count = request_count + 1
            """,
            (actor_id, window_start, window_seconds),
        )
        self._conn.commit()

    def _count(self, actor_id: str, window_seconds: int, window_start: int) -> int:
        row = self._conn.execute(
            """
            SELECT request_count FROM chat_quota
            WHERE actor_id = ? AND window_seconds = ? AND window_start = ?
            """,
            (actor_id, window_seconds, window_start),
        ).fetchone()
        return row[0] if row else 0
