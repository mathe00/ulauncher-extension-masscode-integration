#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Writer Module

This module provides functionality for saving new snippets to MassCode
databases in all supported formats:
  - V3: JSON file (db.json)
  - V4: SQLite database (massCode.db)
  - V5: Markdown Vault (markdown-vault/ directory)

All writes target the MassCode Inbox (unassigned snippets):
  - V3: folderId = null in the snippets array
  - V4: folderId = NULL in the snippets table
  - V5: .masscode/inbox/ directory inside the code space
"""

import json
import os
import re
import sqlite3
import tempfile
import time
import logging
from typing import Dict, Any, Optional

import yaml

from ..constants import (
    MASSCODE_V3,
    MASSCODE_V4,
    MASSCODE_V5,
    VAULT_META_DIR,
    VAULT_STATE_FILE,
    VAULT_CODE_SPACE,
    DEFAULT_SNIPPET_LANGUAGE,
    SNIPPET_NAME_MAX_LEN,
)
from .loader import resolve_vault_space_dir

logger = logging.getLogger(__name__)


# =============================================================================
# PUBLIC API
# =============================================================================


def save_snippet_to_inbox(
    db_path: str,
    masscode_version: str,
    content: str,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Save a new snippet to MassCode Inbox.

    This is the main entry point for the save feature. It dispatches to the
    appropriate version-specific writer based on the configured MassCode version.

    Args:
        db_path: Path to the MassCode database file or vault directory
        masscode_version: MassCode version identifier ("v3", "v4", or "v5")
        content: The snippet content (text to save)
        name: Optional snippet name. If None, auto-generated from content.

    Returns:
        Dict with either:
          {"success": True, "name": str, "path": str}
          {"success": False, "error": str}
    """
    # Auto-generate name if not provided
    if not name or not name.strip():
        name = generate_snippet_name(content)

    name = name.strip()

    try:
        if masscode_version == MASSCODE_V5:
            return _save_v5(db_path, content, name)
        elif masscode_version == MASSCODE_V4:
            return _save_v4(db_path, content, name)
        else:
            return _save_v3(db_path, content, name)
    except Exception as e:
        logger.error(f"Failed to save snippet '{name}': {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# =============================================================================
# V3 WRITER — JSON (db.json)
# =============================================================================


def _save_v3(db_path: str, content: str, name: str) -> Dict[str, Any]:
    """
    Save a new snippet to MassCode V3 JSON database.

    Reads db.json, appends the new snippet to the snippets array, and writes
    back atomically (temp file + os.rename to minimize corruption risk).

    Inbox snippets have folderId = null (unassigned).

    Args:
        db_path: Path to db.json
        content: Snippet content
        name: Snippet name

    Returns:
        {"success": True, "name": str, "path": str} or {"success": False, "error": str}
    """
    expanded_path = os.path.expanduser(db_path)
    logger.info(f"Saving snippet to V3 JSON: {expanded_path}")

    if not os.path.exists(expanded_path):
        return {"success": False, "error": f"JSON DB not found: {expanded_path}"}

    try:
        # Read existing database
        with open(expanded_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        snippets = data.get("snippets", [])

        # Generate ID: max existing + 1, or 1 if empty
        existing_ids = [s.get("id", 0) for s in snippets if isinstance(s.get("id"), int)]
        new_id = max(existing_ids) + 1 if existing_ids else 1

        # Current timestamp in milliseconds (matching MassCode format)
        now_ms = int(time.time() * 1000)

        # Build new snippet entry (V3 format, folderId=null for Inbox)
        new_snippet = {
            "id": new_id,
            "name": name,
            "content": content,
            "isDeleted": False,
            "folderId": None,
            "createdAt": now_ms,
            "updatedAt": now_ms,
        }

        snippets.append(new_snippet)
        data["snippets"] = snippets

        # Atomic write: temp file + rename
        _atomic_write_json(expanded_path, data)

        logger.info(f"Snippet '{name}' saved to V3 JSON (id={new_id}).")
        return {"success": True, "name": name, "path": expanded_path}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON in DB: {e}"}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {expanded_path}"}


# =============================================================================
# V4 WRITER — SQLite (massCode.db)
# =============================================================================


def _save_v4(db_path: str, content: str, name: str) -> Dict[str, Any]:
    """
    Save a new snippet to MassCode V4+ SQLite database.

    Inserts a row into the 'snippets' table (folderId=NULL for Inbox)
    and a corresponding row into 'snippet_contents'.

    SQLite handles concurrent access natively, making this the safest format
    for writing while MassCode is running.

    Args:
        db_path: Path to massCode.db
        content: Snippet content
        name: Snippet name

    Returns:
        {"success": True, "name": str, "path": str} or {"success": False, "error": str}
    """
    expanded_path = os.path.expanduser(db_path)
    logger.info(f"Saving snippet to V4 SQLite: {expanded_path}")

    if not os.path.exists(expanded_path):
        return {"success": False, "error": f"SQLite DB not found: {expanded_path}"}

    try:
        with sqlite3.connect(expanded_path) as conn:
            # Current timestamp in milliseconds (matching MassCode format)
            now_ms = int(time.time() * 1000)

            # Insert snippet (folderId=NULL = Inbox)
            cursor = conn.execute(
                """
                INSERT INTO snippets (name, description, folderId, isDeleted, isFavorites, createdAt, updatedAt)
                VALUES (?, NULL, NULL, 0, 0, ?, ?)
                """,
                (name, now_ms, now_ms),
            )
            snippet_id = cursor.lastrowid

            # Insert snippet content (single fragment)
            conn.execute(
                """
                INSERT INTO snippet_contents (snippetId, label, value, language)
                VALUES (?, ?, ?, ?)
                """,
                (snippet_id, "Fragment 1", content, DEFAULT_SNIPPET_LANGUAGE),
            )

            conn.commit()
            logger.info(
                f"Snippet '{name}' saved to V4 SQLite (id={snippet_id})."
            )
            return {"success": True, "name": name, "path": expanded_path}

    except sqlite3.Error as e:
        return {"success": False, "error": f"SQLite error: {e}"}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {expanded_path}"}


# =============================================================================
# V5 WRITER — Markdown Vault (markdown-vault/)
# =============================================================================


def _save_v5(vault_path: str, content: str, name: str) -> Dict[str, Any]:
    """
    Save a new snippet to MassCode V5+ Markdown Vault.

    Creates a .md file in the code space's .masscode/inbox/ directory with
    proper YAML frontmatter and fenced code block body. Then updates
    state.json to register the new snippet (incrementing counters).

    Supports both vault layouts:
      - Spaces layout: <vault>/code/.masscode/inbox/
      - Legacy flat:   <vault>/.masscode/inbox/

    Args:
        vault_path: Path to the vault root directory
        content: Snippet content
        name: Snippet name

    Returns:
        {"success": True, "name": str, "path": str} or {"success": False, "error": str}
    """
    expanded_path = os.path.expanduser(vault_path)
    logger.info(f"Saving snippet to V5 Markdown Vault: {expanded_path}")

    if not os.path.isdir(expanded_path):
        return {"success": False, "error": f"Vault directory not found: {expanded_path}"}

    # Resolve the correct space directory (code/ for spaces, vault root for legacy)
    space_dir = resolve_vault_space_dir(expanded_path)

    # Locate state.json
    state_file = os.path.join(space_dir, VAULT_META_DIR, VAULT_STATE_FILE)
    if not os.path.isfile(state_file):
        return {
            "success": False,
            "error": f"Vault state file not found: {state_file}",
        }

    # Locate inbox directory
    inbox_dir = os.path.join(space_dir, VAULT_META_DIR, "inbox")
    if not os.path.isdir(inbox_dir):
        try:
            os.makedirs(inbox_dir, exist_ok=True)
            logger.info(f"Created inbox directory: {inbox_dir}")
        except OSError as e:
            return {"success": False, "error": f"Cannot create inbox dir: {e}"}

    try:
        # --- Step 1: Read state.json to get counters ---
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        counters = state.get("counters", {})
        new_snippet_id = counters.get("snippetId", 0) + 1
        new_content_id = counters.get("contentId", 0) + 1
        now_ms = int(time.time() * 1000)

        # --- Step 2: Generate unique filename ---
        slug = _slugify(name)
        md_filename = f"{slug}.md"
        md_filepath = os.path.join(inbox_dir, md_filename)

        # Ensure uniqueness — append -N suffix if file already exists
        counter = 1
        while os.path.exists(md_filepath):
            counter += 1
            md_filename = f"{slug}-{counter}.md"
            md_filepath = os.path.join(inbox_dir, md_filename)

        # --- Step 3: Create the .md file ---
        # Format matches real MassCode V5 snippet files exactly
        md_content = _build_v5_markdown(
            name=name,
            content=content,
            snippet_id=new_snippet_id,
            content_id=new_content_id,
            created_at=now_ms,
            updated_at=now_ms,
        )

        with open(md_filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.debug(f"Created snippet file: {md_filepath}")

        # --- Step 4: Update state.json ---
        # filePath is relative to the space directory (code/)
        relative_file_path = os.path.relpath(md_filepath, space_dir)

        # Append new snippet entry
        snippets_list = state.get("snippets", [])
        snippets_list.append(
            {
                "filePath": relative_file_path,
                "id": new_snippet_id,
            }
        )
        state["snippets"] = snippets_list

        # Increment counters
        counters["snippetId"] = new_snippet_id
        counters["contentId"] = new_content_id
        state["counters"] = counters

        # Atomic write state.json
        _atomic_write_json(state_file, state)

        logger.info(
            f"Snippet '{name}' saved to V5 Vault (id={new_snippet_id}, file={md_filename})."
        )
        return {"success": True, "name": name, "path": md_filepath}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON in state file: {e}"}
    except PermissionError:
        return {"success": False, "error": f"Permission denied writing to vault"}
    except OSError as e:
        return {"success": False, "error": f"File system error: {e}"}


def _build_v5_markdown(
    name: str,
    content: str,
    snippet_id: int,
    content_id: int,
    created_at: int,
    updated_at: int,
) -> str:
    """
    Build a V5 Markdown snippet file content.

    The format matches real MassCode V5 snippet files:
      - YAML frontmatter with metadata and contents[]
      - Body with ## Fragment: heading and fenced code block

    Args:
        name: Snippet display name
        content: The code/text content for the fragment
        snippet_id: Numeric snippet ID (from counters)
        content_id: Numeric content ID (from counters)
        created_at: Creation timestamp in milliseconds
        updated_at: Last update timestamp in milliseconds

    Returns:
        Complete .md file content as string
    """
    # Build YAML frontmatter
    # Using yaml.dump for safe YAML generation (handles special characters)
    frontmatter_data = {
        "contents": [
            {
                "id": content_id,
                "label": "Fragment 1",
                "language": DEFAULT_SNIPPET_LANGUAGE,
            }
        ],
        "createdAt": created_at,
        "description": None,
        "folderId": None,
        "id": snippet_id,
        "isDeleted": 0,
        "isFavorites": 0,
        "name": name,
        "tags": [],
        "updatedAt": updated_at,
    }

    # Use yaml.dump with default_flow_style=False for readable output
    # sort_keys=False preserves the logical ordering
    yaml_str = yaml.dump(
        frontmatter_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()

    # Build the complete markdown file
    md = f"---\n{yaml_str}\n---\n\n## Fragment: Fragment 1\n```{DEFAULT_SNIPPET_LANGUAGE}\n{content}\n```\n"
    return md


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def generate_snippet_name(content: str) -> str:
    """
    Auto-generate a snippet name from the content.

    Strategy:
      1. Take the first non-empty line of content
      2. Trim whitespace and special characters
      3. Truncate to SNIPPET_NAME_MAX_LEN
      4. Fallback to "Snippet <timestamp>" if content is empty or only whitespace

    Args:
        content: The snippet text content

    Returns:
        A generated snippet name string
    """
    if not content or not content.strip():
        return f"Snippet {int(time.time())}"

    # Extract first non-empty line
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped:
            # Remove common code prefixes (comments, shebangs, etc.)
            clean = re.sub(r"^[#//!;*>\-\s]+", "", stripped).strip()
            if clean:
                name = clean[:SNIPPET_NAME_MAX_LEN]
                # Don't cut in the middle of a word — trim to last space
                if len(clean) > SNIPPET_NAME_MAX_LEN and " " in name:
                    name = name[: name.rfind(" ")].rstrip()
                return name if name else f"Snippet {int(time.time())}"

    return f"Snippet {int(time.time())}"


def _slugify(text: str) -> str:
    """
    Convert a snippet name to a filesystem-safe slug.

    Rules:
      - Lowercase
      - Replace non-alphanumeric chars (except spaces, hyphens, underscores) with hyphens
      - Collapse multiple hyphens/spaces into single hyphen
      - Strip leading/trailing hyphens
      - Limit length to 80 chars

    Args:
        text: The text to slugify

    Returns:
        A filesystem-safe slug string
    """
    # Lowercase
    slug = text.lower().strip()
    # Replace non-alphanumeric (except spaces, hyphens, underscores) with hyphens
    slug = re.sub(r"[^\w\s\-]", "-", slug)
    # Collapse multiple hyphens/spaces into single hyphen
    slug = re.sub(r"[\- ]{2,}", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    # Limit length
    if len(slug) > 80:
        slug = slug[:80].rstrip("-")

    return slug or "untitled-snippet"


def _atomic_write_json(file_path: str, data: Any) -> None:
    """
    Write JSON data to a file atomically using temp file + os.rename.

    This minimizes the risk of corruption if MassCode is reading the file
    at the same time. On Linux, os.rename() is atomic within the same
    filesystem.

    Args:
        file_path: Target file path
        data: Data to serialize as JSON

    Raises:
        OSError: If write or rename fails
    """
    dir_path = os.path.dirname(file_path) or "."

    # Write to a temp file in the same directory (same filesystem for atomic rename)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=".masscode_tmp_",
        dir=dir_path,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename (replaces target if exists)
        os.replace(tmp_path, file_path)
        logger.debug(f"Atomic write completed: {file_path}")
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
