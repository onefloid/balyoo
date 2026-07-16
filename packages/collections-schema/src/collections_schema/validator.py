"""A :class:`~collections_core.interfaces.SchemaValidator` backed by ``jsonschema``."""

from __future__ import annotations

from typing import Any

from collections_core.errors import SchemaValidationError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


class JsonSchemaValidator:
    """Validates item data against a JSON Schema (draft 2020-12)."""

    def validate(self, schema: dict[str, Any], data: dict[str, Any]) -> None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if errors:
            raise SchemaValidationError([self._format(e) for e in errors])

    @staticmethod
    def _format(error: JsonSchemaValidationError) -> str:
        path = ".".join(str(part) for part in error.absolute_path)
        return f"{path}: {error.message}" if path else error.message
