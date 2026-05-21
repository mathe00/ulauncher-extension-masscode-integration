#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snippet Cache Module

Provides in-memory caching for loaded snippets with file mtime validation.
Snippets are reloaded only when the source files (state.json for V5, db file
for V3/V4) change on disk. This eliminates redundant I/O on repeated queries.

Usage:
    from ..database.cache import SnippetCache

    snippets = SnippetCache.get_snippets(db_path, masscode_version)
    # First call → loads from disk (cache MISS)
    # Subsequent calls → returns cached data (cache HIT) until source changes
"""

import os
import logging
from typing import List, Dict, Any, Optional

from .loader import load_snippets, resolve_vault_space_dir
from ..constants import VAULT_META_DIR, VAULT_STATE_FILE, MASSCODE_V5

logger = logging.getLogger(__name__)


# ==============================================================================
# MODULE-LEVEL CACHE
# ==============================================================================
# Stored as module-level variables (effectively a singleton) so the cache
# persists across Ulauncher's event handling lifecycle.
#
# We use a class with classmethods rather than bare functions for
# logical grouping and to allow easy mock-based testing.
# ==============================================================================


class SnippetCache:
    """
    In-memory snippet cache with file mtime invalidation.

    Design:
      - Cache lives in module-level class variables (singleton per Python process)
      - On each access, we stat() the authoritative source file (state.json,
        massCode.db, or db.json) to check for modifications
      - If the source hasn't changed AND the db_path/version match → return cache
      - Otherwise → reload from disk, update cache, return fresh data

    Thread safety:
      Ulauncher's event loop processes events sequentially, so there are no
      concurrent access concerns within a single Python process. If Ulauncher
      spawns multiple extension processes, each has its own independent cache
      (which is fine — no cross-process sharing needed).
    """

    _snippets: Optional[List[Dict[str, Any]]] = None
    _source_mtime: float = 0.0
    _db_path: str = ""
    _masscode_version: str = ""

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    @classmethod
    def get_snippets(cls, db_path: str, masscode_version: str) -> List[Dict[str, Any]]:
        """
        Retrieve snippets, using cache if the source hasn't changed.

        Args:
            db_path: Path to the MassCode database/vault (from preferences)
            masscode_version: "v3", "v4", or "v5"

        Returns:
            List of snippet dicts (same format as load_snippets())
        """
        # Resolve the authoritative source file mtime
        current_mtime = cls._resolve_mtime(db_path, masscode_version)

        # Cache HIT — all conditions match, source hasn't changed
        if cls._is_cache_valid(db_path, masscode_version, current_mtime):
            logger.debug(
                "Snippet cache HIT — %d snippets, mtime=%.3f",
                len(cls._snippets) if cls._snippets else 0,
                current_mtime,
            )
            return cls._snippets  # type: ignore[return-value]

        # Cache MISS or source changed — reload from disk
        logger.debug(
            "Snippet cache MISS — (path_changed=%s, version_changed=%s, "
            "mtime_changed=%s)",
            cls._db_path != db_path,
            cls._masscode_version != masscode_version,
            cls._source_mtime != current_mtime,
        )
        return cls._reload(db_path, masscode_version, current_mtime)

    @classmethod
    def invalidate(cls) -> None:
        """
        Force cache invalidation.

        Useful for manual refresh (e.g., a future 'ms refresh' command)
        or in tests to reset state between test cases.
        """
        cls._snippets = None
        cls._source_mtime = 0.0
        cls._db_path = ""
        cls._masscode_version = ""
        logger.debug("Snippet cache explicitly invalidated.")

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    @classmethod
    def _is_cache_valid(
        cls, db_path: str, masscode_version: str, current_mtime: float
    ) -> bool:
        """
        Check whether the cached snippets are still valid.

        Conditions for validity:
          1. Cache is populated (not None)
          2. Same db_path (user didn't change preferences)
          3. Same masscode_version (user didn't switch version)
          4. Source file mtime unchanged (no changes on disk)

        Args:
            db_path: Current db_path to compare
            masscode_version: Current version to compare
            current_mtime: Current source file mtime

        Returns:
            True if cache can be used, False otherwise
        """
        return (
            cls._snippets is not None
            and cls._db_path == db_path
            and cls._masscode_version == masscode_version
            and cls._source_mtime == current_mtime
        )

    @classmethod
    def _reload(
        cls, db_path: str, masscode_version: str, current_mtime: float
    ) -> List[Dict[str, Any]]:
        """
        Reload snippets from disk and update the cache.

        Args:
            db_path: Database/vault path
            masscode_version: Version string
            current_mtime: Current mtime of the authoritative source file

        Returns:
            Freshly loaded snippet list
        """
        logger.info(
            "Reloading snippets from disk (db_path=%s, version=%s)",
            db_path,
            masscode_version,
        )
        snippets = load_snippets(db_path=db_path, masscode_version=masscode_version)
        cls._snippets = snippets
        cls._source_mtime = current_mtime
        cls._db_path = db_path
        cls._masscode_version = masscode_version
        logger.info(
            "Cache updated: %d snippets loaded (mtime=%.3f)",
            len(snippets),
            current_mtime,
        )
        return snippets

    @classmethod
    def _resolve_mtime(cls, db_path: str, masscode_version: str) -> float:
        """
        Get the modification timestamp of the authoritative source file.

        For V5+ Markdown Vault: state.json is the central index — when
        MassCode adds, removes, or modifies a snippet, it updates state.json.
        The mtime of state.json is therefore a reliable proxy for "did any
        snippet change?"

        For V4 SQLite: massCode.db file mtime.
        For V3 JSON: db.json file mtime.

        Args:
            db_path: Path from user preferences
            masscode_version: "v3", "v4", or "v5"

        Returns:
            Modification timestamp (float seconds since epoch), or 0.0 if
            the file doesn't exist or can't be accessed (will trigger a
            reload attempt)
        """
        expanded = os.path.expanduser(db_path)

        if masscode_version == MASSCODE_V5:
            # V5: use state.json as the fingerprint of snippet changes
            # resolve_vault_space_dir handles both spaces and legacy layouts
            try:
                space_dir = resolve_vault_space_dir(expanded)
                state_file = os.path.join(space_dir, VAULT_META_DIR, VAULT_STATE_FILE)
                return cls._safe_mtime(state_file)
            except Exception as e:
                logger.warning("Failed to resolve vault space for mtime check: %s", e)
                return 0.0
        else:
            # V3/V4: use the db file itself
            return cls._safe_mtime(expanded)

    @staticmethod
    def _safe_mtime(path: str) -> float:
        """
        Safely get the mtime of a file, returning 0.0 on any error.

        Returns 0.0 rather than raising, because a missing file will
        trigger a cache miss → load attempt → proper error handling
        downstream in load_snippets().

        Args:
            path: Absolute path to the file

        Returns:
            os.path.getmtime() value, or 0.0 if file doesn't exist
            or an OSError occurred
        """
        try:
            if os.path.exists(path):
                return os.path.getmtime(path)
            return 0.0
        except OSError:
            logger.debug("Could not read mtime for '%s'", path)
            return 0.0
