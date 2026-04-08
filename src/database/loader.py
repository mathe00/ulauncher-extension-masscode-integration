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
    VAULT_FOLDER_META_FILE_LEGACY,
    VAULT_CODE_SPACE,
    VAULT_KNOWN_SPACES,
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
#
# MassCode V5+ uses a "spaces" layout where the vault root contains
# subdirectories like code/, notes/, math/ — each with its own
# .masscode/state.json and folder structure.
#
# Vault structure (current, massCode >= ~5.x with spaces):
#   <vault>/
#     code/                         # "code" space (snippets)
#       .masscode/
#         state.json                # Snippet index (filePaths relative to code/)
#         inbox/                    # Unassigned snippets
#         trash/                    # Deleted snippets
#       <FolderName>/
#         .meta.yaml                # Folder metadata (current format)
#         <SnippetName>.md          # Snippet files
#     notes/                        # "notes" space (notes, not snippets)
#       .masscode/
#         state.json
#
# Legacy vault structure (massCode < 5.x, flat layout):
#   <vault>/
#     .masscode/
#       state.json                  # Snippet index at vault root
#       inbox/
#       trash/
#     <FolderName>/
#       .masscode-folder.yml        # Old folder metadata filename
#       <SnippetName>.md
#
# We support both layouts for backward compatibility.
# =============================================================================


def resolve_vault_space_dir(vault_path: str) -> str:
    """
    Detect the vault layout and return the correct space directory path.

    MassCode V5+ organizes vaults into "spaces" (code/, notes/, math/).
    The snippet data lives in the "code" space. Older vaults have a flat
    layout with .masscode/ directly at the vault root.

    Detection order (matching massCode's own resolveCodeVaultPath logic):
      1. If <vault>/code/.masscode/state.json exists → spaces layout, return <vault>/code/
      2. If <vault>/.masscode/state.json exists → legacy flat layout, return <vault>/
      3. If <vault>/code/ directory exists (even without state.json) → spaces layout
      4. Otherwise → assume legacy flat layout

    Args:
        vault_path: Absolute path to the vault root directory

    Returns:
        The absolute path to the directory containing snippet data
        (either <vault>/code/ for spaces layout, or <vault>/ for legacy)
    """
    # Check for spaces layout: code/.masscode/state.json
    code_state = os.path.join(
        vault_path, VAULT_CODE_SPACE, VAULT_META_DIR, VAULT_STATE_FILE
    )
    if os.path.isfile(code_state):
        logger.debug(f"Detected spaces layout (code/): {vault_path}")
        return os.path.join(vault_path, VAULT_CODE_SPACE)

    # Check for legacy flat layout: .masscode/state.json at vault root
    legacy_state = os.path.join(vault_path, VAULT_META_DIR, VAULT_STATE_FILE)
    if os.path.isfile(legacy_state):
        logger.debug(f"Detected legacy flat layout: {vault_path}")
        return vault_path

    # Fallback: if code/ directory exists, assume spaces layout
    # (state.json might not exist yet for empty vaults)
    code_dir = os.path.join(vault_path, VAULT_CODE_SPACE)
    if os.path.isdir(code_dir):
        logger.debug(f"Detected spaces layout (code/ dir exists): {vault_path}")
        return code_dir

    # Default to vault root (legacy)
    logger.debug(f"Defaulting to legacy flat layout: {vault_path}")
    return vault_path


def is_markdown_vault(path: str) -> bool:
    """
    Check if a directory is a valid MassCode V5+ Markdown Vault.

    Supports both layouts:
      - Spaces layout: <vault>/code/.masscode/state.json
      - Legacy flat:   <vault>/.masscode/state.json

    Args:
        path: Path to the potential vault directory

    Returns:
        True if the path is a valid Markdown Vault, False otherwise
    """
    expanded_path = os.path.expanduser(path)

    # Must be a directory, not a file
    if not os.path.isdir(expanded_path):
        return False

    # Check spaces layout: code/.masscode/state.json
    spaces_state = os.path.join(
        expanded_path, VAULT_CODE_SPACE, VAULT_META_DIR, VAULT_STATE_FILE
    )
    if os.path.isfile(spaces_state):
        return True

    # Check legacy flat layout: .masscode/state.json at vault root
    legacy_state = os.path.join(expanded_path, VAULT_META_DIR, VAULT_STATE_FILE)
    if os.path.isfile(legacy_state):
        return True

    return False


def _read_folder_metadata(folder_path: str) -> Optional[Dict[str, Any]]:
    """
    Read folder metadata from a directory, supporting both file formats.

    MassCode uses .meta.yaml (current) and previously .masscode-folder.yml (legacy).
    The current format uses 'id' as the folder ID key; the legacy format uses
    'masscode_id'. This function handles both.

    Args:
        folder_path: Absolute path to the folder directory

    Returns:
        Parsed metadata dict, or None if no valid metadata found
    """
    # Try current format: .meta.yaml
    meta_path = os.path.join(folder_path, VAULT_FOLDER_META_FILE)
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f)
            if isinstance(meta, dict):
                return meta
        except (yaml.YAMLError, IOError, OSError) as e:
            logger.warning(f"Failed to read .meta.yaml '{meta_path}': {e}")

    # Try legacy format: .masscode-folder.yml
    meta_path_legacy = os.path.join(folder_path, VAULT_FOLDER_META_FILE_LEGACY)
    if os.path.isfile(meta_path_legacy):
        try:
            with open(meta_path_legacy, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f)
            if isinstance(meta, dict):
                # Migrate masscode_id → id for consistent downstream handling
                if "masscode_id" in meta and "id" not in meta:
                    meta["id"] = meta["masscode_id"]
                return meta
        except (yaml.YAMLError, IOError, OSError) as e:
            logger.warning(
                f"Failed to read .masscode-folder.yml '{meta_path_legacy}': {e}"
            )

    return None


def build_folder_lookup(space_dir: str) -> Dict[int, str]:
    """
    Build a mapping of folder_id → folder_name by scanning the vault space.

    MassCode V5 stores folder metadata in .meta.yaml (current) or
    .masscode-folder.yml (legacy) inside each folder directory.
    The current format uses 'id' as the key; legacy uses 'masscode_id'.

    Args:
        space_dir: Absolute path to the space directory (e.g. <vault>/code/)
                   where folders and .masscode/ live side by side

    Returns:
        Dict mapping folder ID (int) to folder name (str).
        Empty dict if no folders found.
    """
    folder_lookup = {}

    try:
        for entry in os.listdir(space_dir):
            entry_path = os.path.join(space_dir, entry)

            # Skip hidden dirs (like .masscode) and non-directories
            if entry.startswith(".") or not os.path.isdir(entry_path):
                continue

            # Read folder metadata (supports both .meta.yaml and .masscode-folder.yml)
            folder_meta = _read_folder_metadata(entry_path)
            if not folder_meta:
                continue

            # Extract folder ID: try 'id' first (current), then 'masscode_id' (legacy)
            folder_id = folder_meta.get("id") or folder_meta.get("masscode_id")
            if folder_id is None:
                continue

            try:
                folder_id = int(folder_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid folder ID in '{entry_path}': {folder_id}")
                continue

            folder_name = folder_meta.get("name", entry)
            folder_lookup[folder_id] = folder_name
            logger.debug(f"Found folder: id={folder_id}, name='{folder_name}'")

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

    Supports both vault layouts:
      - Spaces layout (current): state.json in <vault>/code/.masscode/
        filePaths in state.json are relative to code/
      - Legacy flat layout:      state.json in <vault>/.masscode/
        filePaths in state.json are relative to vault root

    Vault structure (spaces layout):
      <vault>/
        code/                       # Snippet space
          .masscode/state.json      # Snippet index
          .masscode/inbox/          # Unassigned snippets
          .masscode/trash/          # Deleted snippets
          <FolderName>/
            .meta.yaml              # Folder metadata
            <SnippetName>.md        # Snippet files

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

    # Detect layout and resolve the correct space directory
    # For spaces layout this returns <vault>/code/, for legacy it returns <vault>/
    space_dir = resolve_vault_space_dir(expanded_path)
    logger.debug(f"Resolved space directory: {space_dir}")

    # Locate state.json in the space directory
    state_file = os.path.join(space_dir, VAULT_META_DIR, VAULT_STATE_FILE)
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

    # Build folder name lookup from .meta.yaml / .masscode-folder.yml files
    # Folders are in the space directory (code/), not the vault root
    folder_lookup = build_folder_lookup(space_dir)
    logger.debug(f"Found {len(folder_lookup)} folders in vault.")

    # Process each snippet entry
    # filePath in state.json is relative to the space directory (code/),
    # NOT relative to the vault root
    snippets = []
    errors = 0

    for entry in snippet_entries:
        file_path_rel = entry.get("filePath", "")
        if not file_path_rel:
            logger.warning(f"Snippet entry has no filePath: {entry}")
            continue

        # Resolve full path relative to the space directory (code/ for spaces layout)
        # This is the key fix: old code used vault root, but filePaths are
        # relative to the space dir
        full_path = os.path.join(space_dir, file_path_rel)

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

        # Skip deleted snippets (isDeleted can be int 0/1 or bool)
        is_deleted = frontmatter.get("isDeleted", 0)
        if is_deleted and int(is_deleted) != 0:
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
            try:
                folder_name = folder_lookup.get(int(folder_id))
            except (ValueError, TypeError):
                pass

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
