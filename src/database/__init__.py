"""
Database and Snippet Loading Module

This module provides functionality for loading MassCode snippets
from both JSON (V3 and earlier) and SQLite (V4+) database formats.
"""

from .loader import (
    load_snippets,
    load_snippets_json,
    load_snippets_sqlite,
    is_sqlite_file,
    is_json_file,
)

__all__ = [
    "load_snippets",
    "load_snippets_json",
    "load_snippets_sqlite",
    "is_sqlite_file",
    "is_json_file",
]
