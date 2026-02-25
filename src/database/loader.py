#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Loader Module

This module provides functionality for loading MassCode snippets
from both JSON (V3 and earlier) and SQLite (V4+) database formats.
It handles file format detection, validation, and error handling.
"""

import json
import os
import sqlite3
import logging
from typing import List, Dict, Any

from ..constants import (
    MASSCODE_V3,
    MASSCODE_V4,
)

logger = logging.getLogger(__name__)


def load_snippets(
    db_path: str, masscode_version: str = MASSCODE_V3
) -> List[Dict[str, Any]]:
    """
    Load snippets from MassCode database based on version preference.

    This method routes to the appropriate loader based on the user's MassCode version
    preference. For V3 and earlier, it uses JSON format. For V4+, it uses SQLite.

    Args:
        db_path (str): Path to the MassCode database file (db.json for V3, massCode.db for V4+)
        masscode_version (str): Version identifier ("v3" for JSON, "v4" for SQLite)

    Returns:
        List[Dict[str, Any]]: List of snippet dictionaries in the format expected by the search logic

    Note:
        The return format is normalized to match the existing JSON structure for seamless
        compatibility with the rest of the extension's search and display logic.
        Multi-fragment snippets are expanded into separate entries for fragment-level selection.
    """
    if masscode_version == MASSCODE_V4:
        raw_snippets = load_snippets_sqlite(db_path)
    else:
        raw_snippets = load_snippets_json(db_path)

    logger.info(f"Loaded {len(raw_snippets)} snippets from database.")
    return raw_snippets


def load_snippets_json(db_path: str) -> List[Dict[str, Any]]:
    """
    Load snippets from MassCode V3 JSON format.

    This is the original loader for JSON-based databases used in MassCode V3 and earlier.
    Maintains backward compatibility with existing installations.

    Args:
        db_path (str): Path to the MassCode JSON database file (typically db.json)

    Returns:
        List[Dict[str, Any]]: List of snippet dictionaries in V3 format

    Raises:
        FileNotFoundError: When the specified JSON file doesn't exist
        json.JSONDecodeError: When the JSON file is malformed
    """
    expanded_path = os.path.expanduser(db_path)
    logger.debug(f"Loading snippets from JSON: {expanded_path}")

    # Check if file exists
    if not os.path.exists(expanded_path):
        logger.error(f"JSON DB file not found: {expanded_path}")
        return []

    # Check if it's actually a SQLite file (wrong version selected)
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
    """
    Load snippets from MassCode V4+ SQLite database.

    This loader handles the new SQLite-based database format introduced in MassCode V4+.
    It performs the necessary JOIN operations to reconstruct snippet data in a format
    compatible with the existing search logic.

    Args:
        db_path (str): Path to the MassCode SQLite database file (typically massCode.db)

    Returns:
        List[Dict[str, Any]]: List of snippet dictionaries normalized to V3 format for compatibility

    Raises:
        sqlite3.Error: When there are database connectivity or query issues
        FileNotFoundError: When the specified database file doesn't exist

    Note:
        The method transforms the relational SQLite data into the flat structure expected
        by the existing search and display logic, ensuring seamless compatibility.
        For multi-fragment snippets, fragments are preserved with their labels for display
        as separate selectable entries.
    """
    expanded_path = os.path.expanduser(db_path)
    logger.debug(f"Loading snippets from SQLite: {expanded_path}")

    # Validate database file exists
    if not os.path.exists(expanded_path):
        logger.error(f"SQLite DB file not found: {expanded_path}")
        return []

    # Check if it's actually a JSON file (wrong version selected)
    if is_json_file(expanded_path):
        logger.warning(f"File appears to be JSON but V4+ selected: {expanded_path}")
        return []

    try:
        with sqlite3.connect(expanded_path) as conn:
            # Enable row factory for named access
            conn.row_factory = sqlite3.Row

            # Query to get all active snippets with their content fragments
            # Joins folders, snippets, and snippet_contents tables
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
                    # Create new snippet entry
                    snippets_dict[snippet_id] = {
                        "id": snippet_id,
                        "name": row["name"] or "Unnamed",
                        "description": row["description"],
                        "folderId": row["folderId"],
                        "isDeleted": bool(row["isDeleted"]),
                        "isFavorites": bool(row["isFavorites"]),
                        "createdAt": row["createdAt"],
                        "updatedAt": row["updatedAt"],
                        "folder_name": row["folder_name"],
                        "content": [],  # Will hold content fragments
                    }

                # Add content fragment if it exists
                if row["content_value"]:
                    snippets_dict[snippet_id]["content"].append(
                        {
                            "label": row["content_label"] or "",
                            "value": row["content_value"],
                            "language": row["language"] or "plaintext",
                        }
                    )

            # Convert to list format and preserve fragment structure
            snippets = []
            for snippet_data in snippets_dict.values():
                content = snippet_data["content"]

                if not content:
                    # No content fragments - create single entry with empty content
                    snippet = {
                        "name": snippet_data["name"],
                        "content": "",
                        "isDeleted": snippet_data["isDeleted"],
                        "_fragments_content": [],  # Empty list
                    }
                elif len(content) == 1:
                    # Single fragment - use as string for backward compatibility
                    fragment = content[0]
                    snippet = {
                        "name": snippet_data["name"],
                        "content": fragment["value"],
                        "isDeleted": snippet_data["isDeleted"],
                        "_fragments_content": [
                            fragment["value"]
                        ],  # Store single fragment
                        "_fragment_label": fragment["label"]
                        or "",  # Store label for reference
                    }
                else:
                    # Multiple fragments - preserve full structure for fragment-level handling
                    # Create separate entries for accessibility while keeping metadata
                    base_snippet = {
                        "name": snippet_data["name"],
                        "content": content,  # Keep as list for fragment handling
                        "isDeleted": snippet_data["isDeleted"],
                        "_multi_fragment": True,  # Flag for multi-fragment snippets
                    }
                    snippets.append(base_snippet)
                    continue  # Skip the rest of this iteration

                # Add V4-specific metadata as extensions for future use
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
    """
    Check if a file is a SQLite database by reading the first few bytes.

    SQLite files start with the magic bytes "SQLite format 3\000".

    Args:
        file_path (str): Path to the file to check

    Returns:
        bool: True if the file appears to be a SQLite database, False otherwise
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
            # SQLite format 3 magic bytes
            return header.startswith(b"SQLite format 3")
    except (IOError, OSError):
        return False


def is_json_file(file_path: str) -> bool:
    """
    Check if a file is a JSON file by reading the first few bytes.

    JSON files typically start with '{' or '['.

    Args:
        file_path (str): Path to the file to check

    Returns:
        bool: True if the file appears to be a JSON file, False otherwise
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_char = f.read(1)
            return first_char in ["{", "["]
    except (IOError, OSError, UnicodeDecodeError):
        return False
