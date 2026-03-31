#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Loader Module

This module provides functionality for loading MassCode snippets
from JSON (V3 and earlier), SQLite (V4+), and Markdown Vault (V5+) formats.
"""

import json
import os
import re
import sqlite3
import logging
from typing import List, Dict, Any, Tuple, Optional

import yaml

from ..constants import (
    MASSCODE_V3,
    MASSCODE_V4,
    MASSCODE_V5,
    VAULT_META_DIR,
    VAULT_STATE_FILE,
    VAULT_FOLDER_META_FILE,
)

logger = logging.getLogger(__name__)


def load_snippets(
    db_path: str, masscode_version: str = MASSCODE_V3
) -> List[Dict[str, Any]]:
    """Load snippets from MassCode database based on version preference."""
    if masscode_version == MASSCODE_V5:
        snippets = load_snippets_markdown(db_path)
    elif masscode_version == MASSCODE_V4:
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


# =============================================================================
# V5+ Markdown Vault Loader
# =============================================================================


def is_markdown_vault(path: str) -> bool:
    """
    Check if a directory is a valid MassCode V5+ Markdown Vault.

    A vault is identified by the presence of .masscode/state.json
    at the vault root (flat layout, no code/ subdirectory).

    Args:
        path: Path to the potential vault directory

    Returns:
        True if the path is a valid Markdown Vault, False otherwise
    """
    expanded_path = os.path.expanduser(path)

    # Must be a directory, not a file
    if not os.path.isdir(expanded_path):
        return False

    # Check for state.json in .masscode/ subdirectory
    state_file = os.path.join(expanded_path, VAULT_META_DIR, VAULT_STATE_FILE)
    return os.path.isfile(state_file)


def build_folder_lookup(vault_path: str) -> Dict[int, str]:
    """
    Build a mapping of folder_id → folder_name by scanning the vault.

    MassCode V5 stores folder metadata in .masscode-folder.yml files
    inside each folder directory at the vault root. The key field is
    'masscode_id' (not 'id').

    Args:
        vault_path: Absolute path to the vault root directory

    Returns:
        Dict mapping folder ID (int) to folder name (str).
        Empty dict if no folders found.
    """
    folder_lookup = {}

    try:
        for entry in os.listdir(vault_path):
            entry_path = os.path.join(vault_path, entry)

            # Skip hidden dirs and non-directories
            if entry.startswith(".") or not os.path.isdir(entry_path):
                continue

            # Check for .masscode-folder.yml
            meta_file = os.path.join(entry_path, VAULT_FOLDER_META_FILE)
            if not os.path.isfile(meta_file):
                continue

            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    folder_meta = yaml.safe_load(f)

                if folder_meta and "masscode_id" in folder_meta:
                    folder_id = int(folder_meta["masscode_id"])
                    folder_name = folder_meta.get("name", entry)
                    folder_lookup[folder_id] = folder_name
                    logger.debug(f"Found folder: id={folder_id}, name='{folder_name}'")
            except (yaml.YAMLError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse folder metadata '{meta_file}': {e}")
                # Fall back to directory name as folder name
                folder_lookup[entry] = entry

    except OSError as e:
        logger.error(f"Error scanning vault for folders: {e}", exc_info=True)

    return folder_lookup


def parse_snippet_markdown(
    file_path: str,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Parse a single MassCode V5 snippet Markdown file.

    The file format is:
      - YAML frontmatter between --- delimiters (contains metadata + contents[])
      - Body with ## Fragment: <label> headings followed by fenced code blocks

    Args:
        file_path: Absolute path to the .md file

    Returns:
        Tuple of (frontmatter_dict, fragments_list) where:
        - frontmatter_dict: Parsed YAML frontmatter as a dict, or None on error
        - fragments_list: List of {label, value, language} dicts
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except (IOError, OSError, UnicodeDecodeError) as e:
        logger.error(f"Failed to read snippet file '{file_path}': {e}")
        return None, []

    # Split frontmatter from body using regex
    # Format: ---\n<yaml>\n---\n<body>
    frontmatter_match = re.match(
        r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)",
        raw_content,
        re.DOTALL,
    )

    if not frontmatter_match:
        logger.warning(f"No YAML frontmatter found in '{file_path}'")
        return None, []

    yaml_str = frontmatter_match.group(1)
    body = frontmatter_match.group(2)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.safe_load(yaml_str)
        if not isinstance(frontmatter, dict):
            logger.warning(
                f"Frontmatter is not a dict in '{file_path}': {type(frontmatter)}"
            )
            return None, []
    except yaml.YAMLError as e:
        logger.error(f"YAML parse error in '{file_path}': {e}")
        return None, []

    # Extract frontmatter contents[] metadata for fragment labels/languages
    # Each entry: {id: int, label: str, language: str}
    fm_contents = frontmatter.get("contents", [])
    if not isinstance(fm_contents, list):
        fm_contents = []

    # Parse body fragments: ## Fragment: <label> followed by fenced code blocks
    fragments = _parse_body_fragments(body)

    # Merge frontmatter contents metadata with parsed body fragments
    # Match by label; fill in language from frontmatter if not in code fence
    merged_fragments = _merge_fragments(fm_contents, fragments)

    return frontmatter, merged_fragments


def _parse_body_fragments(body: str) -> List[Dict[str, Any]]:
    """
    Parse the Markdown body into fragments.

    Each fragment starts with a ## Fragment: <label> heading
    followed by a fenced code block (```lang ... ```).

    If no ## Fragment: headings are found, the entire body is
    treated as a single fragment (fallback, matching massCode behavior).

    Args:
        body: The Markdown body (after frontmatter)

    Returns:
        List of {label: str, value: str, language: str} dicts
    """
    # Check if there are any ## Fragment: headings
    fragment_pattern = re.compile(r"^##\s+Fragment:\s+(.+)$", re.MULTILINE)
    fragment_headings = list(fragment_pattern.finditer(body))

    if not fragment_headings:
        # No fragment headings — treat entire body as single fragment
        # Try to extract a single fenced code block from the body
        code_block = _extract_first_code_block(body)
        return [{"label": "Fragment 1", "value": code_block, "language": ""}]

    fragments = []

    for i, heading_match in enumerate(fragment_headings):
        label = heading_match.group(1).strip()
        # Body content starts after this heading
        start = heading_match.end()
        # Body content ends at the next heading (or end of body)
        end = (
            fragment_headings[i + 1].start()
            if i + 1 < len(fragment_headings)
            else len(body)
        )
        section = body[start:end].strip()

        # Extract the fenced code block from this section
        code_block = _extract_first_code_block(section)

        fragments.append({"label": label, "value": code_block, "language": ""})

    return fragments


def _extract_first_code_block(text: str) -> str:
    """
    Extract the content of the first fenced code block from text.

    Supports dynamic fence length (3+ backticks).

    Args:
        text: Text containing a fenced code block

    Returns:
        The code block content (without fences), or empty string if none found
    """
    # Match fenced code block: ```lang\n<content>\n```
    # The fence must be at least 3 backticks
    fence_pattern = re.compile(r"^(`{3,})\s*(\S*)\s*\n(.*?)\n\1\s*$", re.DOTALL)
    match = fence_pattern.search(text)

    if match:
        return match.group(3)

    return ""


def _merge_fragments(
    fm_contents: List[Dict[str, Any]],
    body_fragments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merge frontmatter contents[] metadata with body-parsed fragments.

    Matches by label. If a body fragment has no matching frontmatter entry,
    it gets sequential defaults. If a frontmatter entry has no matching
    body fragment, it's included with empty value.

    Args:
        fm_contents: Frontmatter contents list [{id, label, language}, ...]
        body_fragments: Body-parsed fragments [{label, value, language}, ...]

    Returns:
        Merged list of {label, value, language} dicts
    """
    # Build lookup from frontmatter by label
    fm_by_label = {}
    for entry in fm_contents:
        if isinstance(entry, dict) and "label" in entry:
            fm_by_label[entry["label"]] = entry

    merged = []

    for i, body_frag in enumerate(body_fragments):
        label = body_frag["label"]
        value = body_frag["value"]
        body_lang = body_frag.get("language", "")

        if label in fm_by_label:
            # Found matching frontmatter entry — use its language
            fm_entry = fm_by_label[label]
            language = fm_entry.get("language", body_lang) or body_lang
            merged.append({"label": label, "value": value, "language": language})
        else:
            # No frontmatter match — keep body-parsed language
            merged.append({"label": label, "value": value, "language": body_lang})

    return merged


def load_snippets_markdown(vault_path: str) -> List[Dict[str, Any]]:
    """
    Load snippets from a MassCode V5+ Markdown Vault.

    The vault structure is:
      <vault>/
        .masscode/state.json       — Central snippet index
        .masscode/inbox/           — Snippets without a folder
        .masscode/trash/           — Deleted snippets
        <FolderName>/
          .masscode-folder.yml     — Folder metadata
          <SnippetName>.md         — Snippet files

    Each snippet .md file has:
      - YAML frontmatter with metadata (name, isDeleted, contents[], etc.)
      - Body with ## Fragment: headings and fenced code blocks

    Args:
        vault_path: Path to the vault root directory

    Returns:
        List of snippet dicts in V3-compatible format:
        {name, content, isDeleted, _description?, _isFavorites?, _folder?}
    """
    expanded_path = os.path.expanduser(vault_path)
    logger.debug(f"Loading snippets from Markdown Vault: {expanded_path}")

    # Validate vault exists
    if not os.path.isdir(expanded_path):
        logger.error(f"Vault directory not found: {expanded_path}")
        return []

    # Locate state.json
    state_file = os.path.join(expanded_path, VAULT_META_DIR, VAULT_STATE_FILE)
    if not os.path.isfile(state_file):
        logger.error(f"Vault state file not found: {state_file}")
        return []

    # Load state.json to get the snippet index
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in state file '{state_file}': {e}")
        return []
    except Exception as e:
        logger.error(f"Error reading state file '{state_file}': {e}", exc_info=True)
        return []

    snippet_entries = state.get("snippets", [])
    if not snippet_entries:
        logger.info("No snippets found in vault state file.")
        return []

    # Build folder name lookup from .masscode-folder.yml files
    folder_lookup = build_folder_lookup(expanded_path)
    logger.debug(f"Found {len(folder_lookup)} folders in vault.")

    # Process each snippet entry
    snippets = []
    errors = 0

    for entry in snippet_entries:
        file_path_rel = entry.get("filePath", "")
        if not file_path_rel:
            logger.warning(f"Snippet entry has no filePath: {entry}")
            continue

        # Resolve full path relative to vault root
        full_path = os.path.join(expanded_path, file_path_rel)

        if not os.path.isfile(full_path):
            logger.warning(f"Snippet file not found: {full_path}")
            errors += 1
            continue

        # Parse the Markdown file
        frontmatter, fragments = parse_snippet_markdown(full_path)

        if frontmatter is None:
            logger.warning(f"Failed to parse snippet: {full_path}")
            errors += 1
            continue

        # Skip deleted snippets
        if frontmatter.get("isDeleted"):
            logger.debug(f"Skipping deleted snippet: {frontmatter.get('name', '?')}")
            continue

        # Extract snippet name (fall back to filename without .md extension)
        name = frontmatter.get("name")
        if not name:
            name = os.path.splitext(os.path.basename(full_path))[0]

        # Normalize content: 0 → '', 1 → string, 2+ → list
        # Same logic as the V4 SQLite loader for compatibility
        if not fragments:
            content_value = ""
        elif len(fragments) == 1:
            # Single fragment — use as plain string for backward compatibility
            content_value = fragments[0]["value"]
        else:
            # Multiple fragments — preserve as list for fragment-level selection
            content_value = fragments

        # Resolve folder name from folderId
        folder_id = frontmatter.get("folderId")
        folder_name = None
        if folder_id is not None:
            folder_name = folder_lookup.get(int(folder_id))

        # Build V3-compatible snippet dict
        snippet = {
            "name": name,
            "content": content_value,
            "isDeleted": False,  # Already filtered above
        }

        # Add optional V4-style metadata
        description = frontmatter.get("description")
        if description:
            snippet["_description"] = description

        if frontmatter.get("isFavorites"):
            snippet["_isFavorites"] = True

        if folder_name:
            snippet["_folder"] = folder_name

        snippets.append(snippet)

    if errors > 0:
        logger.warning(
            f"Completed with {errors} error(s) while loading Markdown Vault snippets."
        )

    logger.info(f"{len(snippets)} active snippets loaded from Markdown Vault.")
    return snippets
