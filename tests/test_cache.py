"""
Tests for the SnippetCache module.

Tests cover:
  - Cache hit/miss logic (cold start, mtime change, param change)
  - Manual invalidation
  - Edge cases (zero snippets, V5 path errors)
  - Internal helpers (_safe_mtime, _resolve_mtime)

Fixtures are defined in conftest.py:
  - mock_all: mocks load_snippets, getmtime, exists, resolve_vault_space_dir
  - mock_loader: only mocks load_snippets
  - mock_mtime: only mocks os.path.getmtime and os.path.exists
"""

import os
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_DB_PATH = "/fake/vault/markdown-vault"
FAKE_VERSION = "v5"
FAKE_MTIME = 1000.0

FAKE_SNIPPETS_A = [
    {"name": "alpha", "content": "code a", "isDeleted": False},
    {"name": "beta", "content": "code b", "isDeleted": False},
]

FAKE_SNIPPETS_B = [
    {"name": "gamma", "content": "code c", "isDeleted": False},
]


def get_cache():
    """Shortcut to import and return the SnippetCache class."""
    from src.database.cache import SnippetCache

    return SnippetCache


def assert_cache_is_cold(cache_cls):
    """Assert that the cache is in its initial (cold) state."""
    assert cache_cls._snippets is None
    assert cache_cls._source_mtime == 0.0
    assert cache_cls._db_path == ""
    assert cache_cls._masscode_version == ""


# ===========================================================================
# Cold start — first call ever
# ===========================================================================


class TestColdStart:
    """Cache starts cold (empty) and must load on first call."""

    def test_first_call_returns_snippets(self, mock_all):
        """First call should return snippets even if cache is cold."""
        cache = get_cache()
        result = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert result == [{"name": "fake"}]
        assert cache._snippets == result
        assert cache._db_path == FAKE_DB_PATH
        assert cache._masscode_version == FAKE_VERSION
        assert cache._source_mtime > 0

    def test_cache_is_warm_after_first_call(self, mock_all):
        """After first call, internal state should be populated."""
        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert cache._snippets is not None
        assert cache._db_path != ""
        assert cache._masscode_version != ""

    def test_uses_provided_db_path_and_version(self, mock_all):
        """get_snippets should store the exact db_path and version used."""
        cache = get_cache()
        cache.get_snippets("/custom/path", "v3")

        assert cache._db_path == "/custom/path"
        assert cache._masscode_version == "v3"


# ===========================================================================
# Cache HIT — same params, same mtime
# ===========================================================================


class TestCacheHit:
    """When nothing changed, cache should return without reloading."""

    def test_second_call_returns_same_data(self, mock_all, monkeypatch):
        """Two identical calls should return the same list object (reference)."""
        cache = get_cache()
        result1 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        result2 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert result1 is result2, "Should return the exact same list object"

    def test_load_snippets_called_only_once(self, mock_all, monkeypatch):
        """load_snippets should be called only on first call (cache miss)."""
        import src.database.cache as cache_mod

        loader = MagicMock(return_value=FAKE_SNIPPETS_A)
        monkeypatch.setattr(cache_mod, "load_snippets", loader)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # miss → calls loader
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # hit  → no call
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # hit  → no call

        assert loader.call_count == 1, "load_snippets should be called exactly once"

    def test_cache_hit_after_miss_preserves_data(self, mock_all):
        """After a miss + hit, the data from the original load should persist."""
        cache = get_cache()
        result1 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        result2 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        result3 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert result1 == result2 == result3

    def test_consecutive_hits_same_cache_state(self, mock_all):
        """Multiple hits should not corrupt internal cache state."""
        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        for _ in range(10):
            cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert cache._snippets is not None
        assert cache._source_mtime == FAKE_MTIME
        assert cache._db_path == FAKE_DB_PATH
        assert cache._masscode_version == FAKE_VERSION


# ===========================================================================
# Cache MISS — something changed
# ===========================================================================


class TestCacheMiss:
    """Cache should reload on any change (mtime, db_path, version)."""

    def test_mtime_change_triggers_reload(self, mock_all, monkeypatch):
        """When source file mtime changes, cache should reload."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return [{"name": f"call_{call_count}"}]

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        set_mtime = mock_all  # is actually mock_mtime since mock_all returns it

        set_mtime(1000.0)
        cache = get_cache()
        r1 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        set_mtime(2000.0)  # mtime changed!
        r2 = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert call_count == 2, "load_snippets should be called twice"
        assert r1[0]["name"] == "call_1"
        assert r2[0]["name"] == "call_2"

    def test_db_path_change_triggers_reload(self, mock_all, monkeypatch):
        """When db_path changes, cache should reload."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return [{"name": f"call_{call_count}"}]

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        cache = get_cache()
        cache.get_snippets("/first/path", FAKE_VERSION)
        cache.get_snippets("/second/path", FAKE_VERSION)  # different path

        assert call_count == 2

    def test_version_change_triggers_reload(self, mock_all, monkeypatch):
        """When masscode_version changes, cache should reload."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return [{"name": f"call_{call_count}"}]

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, "v3")
        cache.get_snippets(FAKE_DB_PATH, "v5")  # different version

        assert call_count == 2

    def test_all_params_change_triggers_reload(self, mock_all, monkeypatch):
        """Changing all params at once should trigger a single reload."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return [{"name": f"call_{call_count}"}]

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        set_mtime = mock_all

        set_mtime(100.0)
        cache = get_cache()
        cache.get_snippets("/a", "v3")

        set_mtime(200.0)
        cache.get_snippets("/b", "v5")

        assert call_count == 2


# ===========================================================================
# Manual invalidation
# ===========================================================================


class TestInvalidate:
    """invalidate() should force a cache miss on the next call."""

    def test_invalidate_between_calls(self, mock_all, monkeypatch):
        """Calling invalidate() between two identical calls should force reload."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return [{"name": f"call_{call_count}"}]

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # call 1
        cache.invalidate()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # call 2 (forced miss)

        assert call_count == 2

    def test_invalidate_resets_all_state(self):
        """After invalidate(), all internal fields should be back to defaults."""
        cache = get_cache()
        cache._snippets = ["something"]
        cache._source_mtime = 999.0
        cache._db_path = "/some/path"
        cache._masscode_version = "v3"

        cache.invalidate()

        assert cache._snippets is None
        assert cache._source_mtime == 0.0
        assert cache._db_path == ""
        assert cache._masscode_version == ""

    def test_invalidate_then_get_is_cold_start(self, mock_all):
        """After invalidate(), a get_snippets call should be treated as cold."""
        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        cache.invalidate()
        assert_cache_is_cold(cache)

        # Next call should work as if it's the first time
        result = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)
        assert result is not None

    def test_multiple_invalidates_are_safe(self):
        """Calling invalidate() multiple times should not raise."""
        cache = get_cache()
        for _ in range(5):
            cache.invalidate()

        assert_cache_is_cold(cache)


# ===========================================================================
# Internal helper: _safe_mtime
# ===========================================================================


class TestSafeMtime:
    """_safe_mtime should handle filesystem edge cases gracefully."""

    def test_returns_mtime_for_existing_file(self, monkeypatch):
        """If file exists, _safe_mtime should return its mtime."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(os.path, "exists", lambda p: True)
        monkeypatch.setattr(os.path, "getmtime", lambda p: 12345.0)

        result = SnippetCache._safe_mtime("/some/file")
        assert result == 12345.0

    def test_returns_zero_for_missing_file(self, monkeypatch):
        """If file doesn't exist, _safe_mtime should return 0.0."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(os.path, "exists", lambda p: False)

        result = SnippetCache._safe_mtime("/nonexistent/file")
        assert result == 0.0

    def test_returns_zero_on_os_error(self, monkeypatch):
        """If getmtime raises OSError, _safe_mtime should return 0.0."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(os.path, "exists", lambda p: True)
        monkeypatch.setattr(os.path, "getmtime", mock_oserror)

        result = SnippetCache._safe_mtime("/restricted/file")
        assert result == 0.0

    def test_does_not_raise_on_any_error(self, monkeypatch):
        """_safe_mtime should never raise, regardless of input."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(os.path, "exists", mock_oserror)
        monkeypatch.setattr(os.path, "getmtime", mock_oserror)

        # Should not raise
        result = SnippetCache._safe_mtime("/any/path")
        assert result == 0.0

    def test_empty_string_path(self, monkeypatch):
        """_safe_mtime should handle empty string path without crashing."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(os.path, "exists", lambda p: False)

        result = SnippetCache._safe_mtime("")
        assert result == 0.0


# ===========================================================================
# Internal helper: _resolve_mtime
# ===========================================================================


class TestResolveMtime:
    """_resolve_mtime should find the right source file for each version."""

    def test_v5_uses_state_json(self, monkeypatch):
        """V5 should resolve state.json via resolve_vault_space_dir."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(
            SnippetCache,
            "_safe_mtime",
            lambda p: 5000.0 if p.endswith("state.json") else 0.0,
        )

        result = SnippetCache._resolve_mtime("/vault", "v5")
        assert result == 5000.0

    def test_v4_uses_db_file(self, monkeypatch):
        """V4 should check the mtime of the .db file directly."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(
            SnippetCache,
            "_safe_mtime",
            lambda p: 4000.0 if p.endswith(".db") else 0.0,
        )

        result = SnippetCache._resolve_mtime("/path/massCode.db", "v4")
        assert result == 4000.0

    def test_v3_uses_json_file(self, monkeypatch):
        """V3 should check the mtime of db.json file directly."""
        from src.database.cache import SnippetCache

        monkeypatch.setattr(
            SnippetCache,
            "_safe_mtime",
            lambda p: 3000.0 if p.endswith(".json") else 0.0,
        )

        result = SnippetCache._resolve_mtime("/path/db.json", "v3")
        assert result == 3000.0

    def test_v5_error_fallback(self, monkeypatch):
        """If resolve_vault_space_dir fails, _resolve_mtime should return 0.0."""
        import src.database.cache as cache_mod

        # resolve_vault_space_dir is a module-level import, not a class attr
        # We must patch it at the module level
        monkeypatch.setattr(cache_mod, "resolve_vault_space_dir", mock_oserror)

        # Should not raise
        result = cache_mod.SnippetCache._resolve_mtime("/vault", "v5")
        assert result == 0.0

    def test_expands_user_path(self, monkeypatch):
        """_resolve_mtime should expand ~ in paths."""
        from src.database.cache import SnippetCache

        called_with = []

        def capturing_safe_mtime(path):
            called_with.append(path)
            return 1.0

        monkeypatch.setattr(SnippetCache, "_safe_mtime", capturing_safe_mtime)

        SnippetCache._resolve_mtime("~/massCode/massCode.db", "v4")
        assert any("massCode.db" in p for p in called_with)
        # Path should be expanded (no ~)
        assert all("~" not in p for p in called_with)


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Unusual but valid scenarios."""

    def test_empty_snippets_list(self, mock_all, monkeypatch):
        """If load_snippets returns [], cache should store []."""
        import src.database.cache as cache_mod

        monkeypatch.setattr(cache_mod, "load_snippets", lambda **kw: [])

        cache = get_cache()
        result = cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)

        assert result == []
        assert cache._snippets == []

    def test_cache_with_none_db_path(self, mock_loader, mock_mtime, mock_vault_path):
        """get_snippets with None db_path should raise TypeError (validation
        for None happens upstream in listeners.py before cache is called)."""
        cache = get_cache()
        with pytest.raises(TypeError):
            cache.get_snippets(None, "v5")

    def test_extremely_long_db_path(self, mock_all):
        """Cache should handle very long paths without issues."""
        cache = get_cache()
        long_path = "/" + "a" * 500
        cache.get_snippets(long_path, "v5")

        assert cache._db_path == long_path

    def test_special_characters_in_path(self, mock_all):
        """Cache should handle paths with special characters."""
        cache = get_cache()
        special_path = "/home/user/massCode/backup (2024)/snippets!"
        cache.get_snippets(special_path, "v5")

        assert cache._db_path == special_path

    def test_version_edge_values(self, mock_all, monkeypatch):
        """Cache should handle various version string formats."""
        import src.database.cache as cache_mod

        call_count = 0

        def counting_loader(**kw):
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(cache_mod, "load_snippets", counting_loader)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, "v5")
        cache.get_snippets(FAKE_DB_PATH, "v5")
        cache.get_snippets(FAKE_DB_PATH, "V5")  # uppercase — different!
        cache.get_snippets(FAKE_DB_PATH, "")  # empty string
        cache.get_snippets(FAKE_DB_PATH, "v5")

        # Count: v5(1) + V5(1) + ""(1) + v5 again(1) = 4
        # V5 != v5 (case-sensitive), "" != V5, v5 != "" — each is a miss
        assert call_count == 4


# ===========================================================================
# Integration-style tests (light mocking)
# ===========================================================================


class TestIntegration:
    """Tests that verify the interaction between cache components."""

    def test_mtime_alone_is_not_enough_for_hit(self, mock_all):
        """
        Same mtime but different params should still be a miss.

        This tests that the cache checks ALL conditions, not just mtime.
        """
        cache = get_cache()
        cache.get_snippets("/path/a", "v5")

        # Same mtime, different path → should be a miss
        cache.get_snippets("/path/b", "v5")
        assert cache._db_path == "/path/b"

    def test_cache_hit_logs_debug(self, mock_all, caplog):
        """Cache HIT should be logged at DEBUG level."""
        import logging

        caplog.set_level(logging.DEBUG)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # warm up
        caplog.clear()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # should be HIT

        assert any("cache HIT" in msg for msg in caplog.messages)

    def test_cache_miss_logs_info(self, mock_all, caplog):
        """Cache MISS should be logged at INFO level."""
        import logging

        caplog.set_level(logging.INFO)

        cache = get_cache()
        cache.get_snippets(FAKE_DB_PATH, FAKE_VERSION)  # first call → MISS

        assert any("Reloading snippets" in msg for msg in caplog.messages)

    def test_invalidate_logs_debug(self, caplog):
        """Invalidate should be logged at DEBUG level."""
        import logging

        caplog.set_level(logging.DEBUG)

        cache = get_cache()
        caplog.clear()
        cache.invalidate()

        assert any("invalidated" in msg for msg in caplog.messages)


# ===========================================================================
# Helpers used across tests
# ===========================================================================


def mock_oserror(*args, **kwargs):
    """Callable that raises OSError to simulate I/O failures."""
    raise OSError("Simulated I/O error")
