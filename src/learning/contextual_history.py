#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contextual Learning Module

This module provides functionality for tracking user selections
and enabling contextual autocomplete that learns from usage patterns.
It manages the context history file and provides methods for
loading, saving, and updating history data.

Thread safety: Uses fcntl.flock (Linux file locking) to prevent
concurrent read/write races when multiple Ulauncher events fire
in quick succession.
"""

import fcntl
import json
import logging
import os
import tempfile
from typing import Dict

from ..constants import HISTORY_FILE, MAX_HISTORY_QUERIES


logger = logging.getLogger(__name__)


# =============================================================================
# INTERNAL HELPERS — file locking and atomic I/O
# =============================================================================


def _acquire_lock(lock_path: str):
    """
    Create and acquire an exclusive file lock.

    Uses fcntl.flock on a separate .lock file to coordinate access
    between concurrent Ulauncher event processes.

    Args:
        lock_path: Path to the .lock file

    Returns:
        The open lock file descriptor (caller must close to release)
    """
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except (OSError, IOError):
        # If locking fails (e.g., NFS, read-only FS), proceed without lock
        # Better to work without locking than to crash entirely
        logger.warning(
            "File locking failed for %s — proceeding without lock", lock_path
        )
    return lock_fd


def _release_lock(lock_fd):
    """
    Release a previously acquired file lock.

    Args:
        lock_fd: The file descriptor returned by _acquire_lock
    """
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    except (OSError, IOError):
        pass
    finally:
        lock_fd.close()


def _atomic_write_json(file_path: str, data: dict) -> None:
    """
    Write JSON data atomically using temp file + os.replace.

    This prevents corruption if the process crashes mid-write.

    Args:
        file_path: Target file path
        data: Data to serialize as JSON
    """
    dir_path = os.path.dirname(file_path) or "."
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=".masscode_history_tmp_",
        dir=dir_path,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _validate_history(data: dict) -> dict:
    """
    Validate and sanitize loaded history data.

    Ensures the loaded JSON has the expected structure:
      { "query_str": { "snippet_name": int_count, ... }, ... }

    Removes malformed entries instead of discarding the entire file.

    Args:
        data: Raw loaded JSON data

    Returns:
        Sanitized history dict
    """
    if not isinstance(data, dict):
        return {}

    clean = {}
    for query, snippets in data.items():
        if not isinstance(query, str) or not isinstance(snippets, dict):
            continue
        # Filter snippet entries: only keep string→int pairs
        valid_snippets = {
            k: v
            for k, v in snippets.items()
            if isinstance(k, str) and isinstance(v, (int, float))
        }
        if valid_snippets:
            clean[query] = valid_snippets

    return clean


# =============================================================================
# PUBLIC API
# =============================================================================


def ensure_history_file_exists(history_file_path: str = HISTORY_FILE) -> None:
    """
    Ensure the history file exists by creating an empty one if needed.

    Args:
        history_file_path: Path to the history file. Defaults to HISTORY_FILE.
    """
    if not os.path.exists(history_file_path):
        logger.info("Creating history file: %s", history_file_path)
        try:
            _atomic_write_json(history_file_path, {})
        except Exception as e:
            logger.error("Unable to create history file: %s", e, exc_info=True)


def load_context_history(
    history_file_path: str = HISTORY_FILE,
) -> Dict[str, Dict[str, int]]:
    """
    Load the context history from file.

    Args:
        history_file_path: Path to the history file. Defaults to HISTORY_FILE.

    Returns:
        Dict mapping queries to snippets and their selection counts.
        Returns empty dict if file doesn't exist or is corrupted.
    """
    if not os.path.exists(history_file_path):
        return {}

    lock_path = history_file_path + ".lock"
    lock_fd = _acquire_lock(lock_path)
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        history = _validate_history(raw)
        logger.debug("History loaded (%d queries).", len(history))
        return history
    except json.JSONDecodeError:
        logger.warning("Invalid history JSON '%s'. Resetting.", history_file_path)
        try:
            _atomic_write_json(history_file_path, {})
        except Exception as save_e:
            logger.error("Unable to reset corrupted history: %s", save_e)
        return {}
    except Exception as e:
        logger.error("Error loading history: %s", e, exc_info=True)
        return {}
    finally:
        _release_lock(lock_fd)


def save_context_history(
    history_data: Dict[str, Dict[str, int]],
    history_file_path: str = HISTORY_FILE,
) -> None:
    """
    Save the context history to file atomically.

    Args:
        history_data: History data to save
        history_file_path: Path to the history file. Defaults to HISTORY_FILE.
    """
    logger.debug(
        "Saving history (%d queries) to %s", len(history_data), history_file_path
    )

    lock_path = history_file_path + ".lock"
    lock_fd = _acquire_lock(lock_path)
    try:
        _atomic_write_json(history_file_path, history_data)
    except Exception as e:
        logger.error("Error saving history: %s", e, exc_info=True)
    finally:
        _release_lock(lock_fd)


def update_context_history(
    query: str,
    snippet_name: str,
    fragment_label: str = "",
    enable_contextual_learning: bool = True,
    history_file_path: str = HISTORY_FILE,
) -> None:
    """
    Update contextual learning history with user selection.

    This method tracks which snippets are selected for which queries,
    enabling the smart autocomplete to learn from usage patterns.

    Thread-safe: acquires a file lock for the entire load→modify→save cycle.

    Args:
        query: The search query used by the user
        snippet_name: The name of the snippet selected
        fragment_label: The fragment label if selecting a specific fragment
        enable_contextual_learning: Whether contextual learning is enabled
        history_file_path: Path to the history file. Defaults to HISTORY_FILE.

    Note:
        History keys are formatted as "snippet_name" for single-fragment
        snippets or "snippet_name [fragment_label]" for fragment-level
        selections.
    """
    if not enable_contextual_learning:
        logger.debug("Contextual learning disabled, history not updated.")
        return

    normalized_query = query.lower().strip()
    if not normalized_query or not snippet_name:
        logger.warning("Attempting to update history with empty query or snippet name.")
        return

    # Acquire lock for the entire read-modify-write cycle
    lock_path = history_file_path + ".lock"
    lock_fd = _acquire_lock(lock_path)
    try:
        # Load current history (inside lock)
        history = {}
        if os.path.exists(history_file_path):
            try:
                with open(history_file_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                history = _validate_history(raw)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Could not load history for update, starting fresh: %s", e
                )
                history = {}

        # snippet_name already includes fragment label if present
        # (e.g., "my snippet [Fragment 1]")
        history_key = snippet_name

        logger.info(
            "Updating History: Query='%s', Snippet='%s'", normalized_query, history_key
        )

        if normalized_query not in history:
            history[normalized_query] = {}
        history[normalized_query][history_key] = (
            history[normalized_query].get(history_key, 0) + 1
        )

        # Prune oldest queries if over limit
        if len(history) > MAX_HISTORY_QUERIES:
            logger.info("Pruning history (limit %d).", MAX_HISTORY_QUERIES)
            keys_to_del = list(history.keys())[:-MAX_HISTORY_QUERIES]
            for k in keys_to_del:
                del history[k]

        # Atomic write (still inside lock)
        _atomic_write_json(history_file_path, history)

    except Exception as e:
        logger.error("Error updating history: %s", e, exc_info=True)
    finally:
        _release_lock(lock_fd)
