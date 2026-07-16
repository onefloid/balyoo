"""Command-line composition layer.

The CLI is where a concrete storage provider, validator and service are wired
together -- the core never assembles itself.
"""

from collections_cli.main import app, main

__all__ = ["app", "main"]
