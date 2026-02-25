#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Loader Module

This module provides functionality for loading MassCode snippets
from both JSON (V3 and earlier) and SQLite (V4+) database formats.
"""

import json
import os
import sqlite3
import logging
from typing import List, Dict, Any

from ..constants import MASSCODE_V3, MASSCODE_V4

logger = logging.getLogger(__name__)


def load_snippets(
    db_path: str, masscode_version: str = MASSCODE_V3
) -> List[Dict[str, Any]]:
    """Load snippets from MassCode database based on version preference."""
    if masscode_version == MASSCODE_V4:
        snippets = load_snippets_sqlite(db_path)
    else:
        snippets = load_snippets_json(db_path)

    logger.info(f"Loaded {len(snippets)} snippets from database.")
    return snippets


def load_snippets_json(db_path: str) -> List[Dict[str, Any]]:
    """Load snippets from MassCode V3 JSON format."""
    expanded_path = os.path.expanduser(db_path)
    logger.debug(f"Loading snippets from JSON: {expanded_path}")

    if not os.path.exists(expanded_path):
        logger.error(f"JSON DB file not found: {expanded_path}")
        return []

    if is_sqlite_file(expanded_path):
        logger.warning(
            f"File appears to be SQLite but V3/earlier selected: {expanded_path}"
        )
        return []

    try:
        with open(expanded_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        snippets = [
            s for s in data.get("snippets", []) if not s.get("isDeleted", False)
        ]
        logger.info(f"{len(snippets)} active snippets loaded from JSON.")
        return snippets
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {expanded_path}")
        return []
    except Exception as e:
        logger.error(f"Error loading JSON snippets: {e}", exc_info=True)
        return []


def load_snippets_sqlite(db_path: str) -> List[Dict[str, Any]]:
    """Load snippets from MassCode V4+ SQLite database."""
    expanded_path = os.path.expanduser(db_path)
    logger.debug(f"Loading snippets from SQLite: {expanded_path}")

    if not os.path.exists(expanded_path):
        logger.error(f"SQLite DB file not found: {expanded_path}")
        return []

    if is_json_file(expanded_path):
        logger.warning(f"File appears to be JSON but V4+ selected: {expanded_path}")
        return []

    try:
        with sqlite3.connect(expanded_path) as conn:
            conn.row_factory = sqlite3.Row

            query = """
            SELECT
                s.id, s.name, s.description, s.folderId, s.isDeleted, s.isFavorites,
                s.createdAt, s.updatedAt,
                f.name as folder_name,
                sc.label as content_label, sc.value as content_value, sc.language
            FROM snippets s
            LEFT JOIN folders f ON s.folderId = f.id
            LEFT JOIN snippet_contents sc ON s.id = sc.snippetId
            WHERE s.isDeleted = 0
            ORDER BY s.id, sc.label
            """

            cursor = conn.execute(query)
            rows = cursor.fetchall()

            if not rows:
                logger.info("No active snippets found in SQLite database.")
                return []

            # Group content fragments by snippet
            snippets_dict = {}
            for row in rows:
                snippet_id = row["id"]

                if snippet_id not in snippets_dict:
                    snippets_dict[snippet_id] = {
                        "id": snippet_id,
                        "name": row["name"] or "Unnamed",
                        "description": row["description"],
                        "folderId": row["folderId"],
                        "isDeleted": bool(row["isDeleted"]),
                        "isFavorites": bool(row["isFavorites"]),
                        "folder_name": row["folder_name"],
                        "content": [],
                    }

                if row["content_value"]:
                    snippets_dict[snippet_id]["content"].append(
                        {
                            "label": row["content_label"] or "",
                            "value": row["content_value"],
                            "language": row["language"] or "plaintext",
                        }
                    )

            # Convert to list format - PRESERVE fragment structure for multi-fragment support
            snippets = []
            for snippet_data in snippets_dict.values():
                content = snippet_data["content"]

                if not content:
                    # No content fragments - use empty string
                    content_value = ""
                elif len(content) == 1:
                    # Single fragment - use as string for backward compatibility
                    content_value = content[0]["value"]
                else:
                    # Multiple fragments - PRESERVE as list for fragment-level selection
                    # Each fragment will be expanded later into separate selectable items
                    content_value = content

                # Create V3-compatible snippet structure
                snippet = {
                    "name": snippet_data["name"],
                    "content": content_value,
                    "isDeleted": snippet_data["isDeleted"],
                }

                # Add V4-specific metadata
                if snippet_data["description"]:
                    snippet["_description"] = snippet_data["description"]
                if snippet_data["isFavorites"]:
                    snippet["_isFavorites"] = True
                if snippet_data["folder_name"]:
                    snippet["_folder"] = snippet_data["folder_name"]

                snippets.append(snippet)

            logger.info(f"{len(snippets)} active snippets loaded from SQLite.")
            return snippets

    except sqlite3.Error as e:
        logger.error(f"SQLite error loading snippets: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading SQLite snippets: {e}", exc_info=True)
        return []


def is_sqlite_file(file_path: str) -> bool:
    """Check if a file is a SQLite database."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
            return header.startswith(b"SQLite format 3")
    except (IOError, OSError):
        return False


def is_json_file(file_path: str) -> bool:
    """Check if a file is a JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_char = f.read(1)
            return first_char in ["{", "["]
    except (IOError, OSError, UnicodeDecodeError):
        return False
