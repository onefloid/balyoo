"""A :class:`~collections_core.interfaces.SchemaValidator` backed by ``jsonschema``."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from collections_core.errors import SchemaValidationError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

# Upper bound on a single regex ``pattern`` string. Long patterns are both a smell
# and a way to hide an expensive construct; a schema field pattern is realistically
# well under this.
_MAX_PATTERN_LENGTH = 1000

# The textbook catastrophic-backtracking shape: a group that already contains an
# unbounded quantifier and is *itself* quantified -- e.g. ``(a+)+``, ``(a*)*``,
# ``(.*)+``, ``(a+){2,}``. Matching a non-matching suffix against these blows up
# exponentially. This is a heuristic (it does not catch every pathological regex),
# so it is a defence-in-depth layer, not the sole guarantee.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[*+][^()]*\)\s*(?:[*+]|\{)")


class JsonSchemaValidator:
    """Validates item data against a JSON Schema (draft 2020-12)."""

    def validate(self, schema: dict[str, Any], data: dict[str, Any]) -> None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if errors:
            raise SchemaValidationError([self._format(e) for e in errors])

    def check_schema(self, schema: dict[str, Any]) -> None:
        """Validate that ``schema`` is itself a well-formed, safe JSON Schema.

        Used before a collection's schema is persisted, so a malformed schema is
        rejected up front rather than surfacing later as opaque validation errors.
        The custom ``x-`` extension keys (``x-collection``, ``x-card``) are ignored
        here, as draft 2020-12 permits unknown keywords.

        This is also the trust boundary for a *client-supplied* schema: once stored,
        the schema's regexes run server-side against every item on validation. To
        keep a malicious or careless schema from wedging a worker with a
        catastrophic-backtracking regex (ReDoS), every ``pattern`` is checked for
        being compilable, bounded in length, and free of the classic nested-quantifier
        construct. Rejecting here is the mitigation, because a runaway ``re`` match
        cannot be reliably interrupted once it has started.
        """
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as error:
            path = ".".join(str(part) for part in error.absolute_path)
            message = f"{path}: {error.message}" if path else error.message
            raise SchemaValidationError([message]) from error

        problems = [msg for pattern in _iter_patterns(schema)
                    for msg in self._pattern_problem(pattern)]
        if problems:
            raise SchemaValidationError(problems)

    @staticmethod
    def _pattern_problem(pattern: str) -> list[str]:
        """A one-item list describing why ``pattern`` is unsafe, or empty if it is fine."""
        if len(pattern) > _MAX_PATTERN_LENGTH:
            return [f"pattern: regex too long (>{_MAX_PATTERN_LENGTH} chars)"]
        try:
            re.compile(pattern)
        except re.error as error:
            return [f"pattern: invalid regex ({error})"]
        if _NESTED_QUANTIFIER.search(pattern):
            return [
                "pattern: rejected as potentially catastrophic (nested quantifier "
                f"like (a+)+): {pattern!r}"
            ]
        return []

    @staticmethod
    def _format(error: JsonSchemaValidationError) -> str:
        path = ".".join(str(part) for part in error.absolute_path)
        return f"{path}: {error.message}" if path else error.message


def _iter_patterns(node: Any) -> Iterator[str]:
    """Yield every regex string a schema will hand to ``re`` -- the values of
    ``pattern`` and the keys of ``patternProperties``, anywhere in the schema tree."""
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            yield pattern
        pattern_props = node.get("patternProperties")
        if isinstance(pattern_props, dict):
            yield from (key for key in pattern_props if isinstance(key, str))
        for value in node.values():
            yield from _iter_patterns(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_patterns(item)
