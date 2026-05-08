#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# START OF FILE/SCRIPT: masscode_extension.py
# DESCRIPTION: ULauncher extension for searching and copying snippets
#              from MassCode, with optional contextual learning and
#              smart single result display.
#              Now refactored into modular architecture.
# ==============================================================================

import os
import sys
import logging
import traceback
import importlib.util

# ==============================================================================
# EARLY STDERR LOGGING — must be set up BEFORE anything else
# ==============================================================================
# This ensures that ANY crash (even during imports) is logged to stderr,
# which Ulauncher can capture in ~/.local/share/ulauncher/last.log.
# Without this, import failures are completely silent (exit code 1, no log).
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
_logger = logging.getLogger("masscode-boot")

# ==============================================================================
# SAFE LIBS LOADING — Prevent compiled .so conflicts with Ulauncher's runtime
# ==============================================================================
# Ulauncher adds the extension's root directory AND the libs/ subdirectory to
# sys.path. If libs/ contains compiled C extensions (like Levenshtein .so files)
# built for a different Python version, they crash the extension at import time
# because Ulauncher's own code imports the same modules transitively.
#
# Strategy: Remove libs/ from its Ulauncher-assigned position, then append it
# at the END of sys.path (lowest priority). System packages are always preferred.
# Our pure-Python libs (fuzzywuzzy, pyyaml, pyperclip) are found in libs/ only
# if not already installed system-wide.
#
# This fixes: https://github.com/mathe00/ulauncher-extension-masscode-integration/issues/4
# ==============================================================================
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBS_DIR = os.path.join(_EXT_DIR, "libs")
_SRC_DIR = os.path.join(_EXT_DIR, "src")

# Add src/ to the front of sys.path for our module imports
sys.path.insert(0, _SRC_DIR)

# Ensure libs/ is at the END of sys.path (low priority)
# This prevents compiled .so leftovers in libs/ from shadowing Ulauncher's
# system-installed packages (e.g., Levenshtein, yaml C extension).
if _LIBS_DIR in sys.path:
    sys.path.remove(_LIBS_DIR)
sys.path.append(_LIBS_DIR)

# ==============================================================================
# RESILIENT IMPORTS — all wrapped in try/except for crash diagnostics
# ==============================================================================
# Every import that could fail (missing dependency, incompatible .so, etc.)
# is wrapped so the user gets a clear error message in Ulauncher's log instead
# of a silent "exit code 1" crash.
# ==============================================================================

# --- Ulauncher API imports (these should always work if Ulauncher is running) ---
try:
    from ulauncher.api.client.Extension import Extension  # noqa: E402
    from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent  # noqa: E402
except ImportError as e:
    _logger.critical(
        "FATAL: Cannot import Ulauncher API. "
        "Ensure Ulauncher is running and API v2 is available. Error: %s",
        e,
    )
    sys.exit(1)

# --- Try to use Ulauncher's logger (preferred), keep our fallback ---
try:
    from ulauncher.api.client.utils import get_logger

    logger = get_logger(__name__)
except ImportError:
    # Keep the basic logging we set up above — it writes to stderr
    logger = logging.getLogger(__name__)

# --- Check optional dependencies early and warn ---
FUZZY_AVAILABLE = importlib.util.find_spec("fuzzywuzzy") is not None
if not FUZZY_AVAILABLE:
    _logger.warning(
        "Optional dependency 'fuzzywuzzy' not found. "
        "Fuzzy matching will use basic substring search. "
        "Install with: pip install fuzzywuzzy -t libs/"
    )

# --- Our modular architecture imports (can fail if libs/ is missing) ---
try:
    from src.events.listeners import KeywordQueryEventListener, ItemEnterEventListener  # noqa: E402
    from src.learning.contextual_history import ensure_history_file_exists  # noqa: E402
except ImportError as e:
    _logger.critical(
        "FATAL: Cannot import extension modules. "
        "This usually means a dependency is missing from libs/. "
        "Run: pip install -r requirements.txt -t libs/  |  Error: %s\n"
        "Extension dir: %s\nlibs/ dir: %s (exists: %s)",
        e,
        _EXT_DIR,
        _LIBS_DIR,
        os.path.isdir(_LIBS_DIR),
    )
    # Print traceback to stderr for full diagnostics
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)


# ==============================================================================
# MAIN CLASS OF THE EXTENSION
# ==============================================================================
class MassCodeExtension(Extension):
    """
    Main extension class for MassCode snippet search.

    This class acts as a thin orchestrator that coordinates the various
    modules of the extension. The actual logic is delegated to:
    - src/database.loader: Snippet loading from JSON/SQLite/Markdown Vault
    - src/learning.contextual_history: Contextual learning and history
    - src/events.listeners: Event handling for queries and selections
    - src/utils.fuzzy_search: Fuzzy matching and relevance scoring
    - src/results.builder: Result item construction
    - src/fragments.fragment_utils: Multi-fragment handling
    - src/database.writer: Saving new snippets to MassCode Inbox
    """

    def __init__(self):
        logger.info("Initializing MassCodeExtension (Refactored)")
        super(MassCodeExtension, self).__init__()

        # Initialize event listeners
        self.keyword_query_listener = KeywordQueryEventListener()
        self.item_enter_listener = ItemEnterEventListener()

        # Subscribe to events
        self.subscribe(KeywordQueryEvent, self.keyword_query_listener)
        self.subscribe(ItemEnterEvent, self.item_enter_listener)

        # Ensure history file exists if contextual learning is enabled
        if self.preferences.get("enable_contextual_learning") == "true":
            ensure_history_file_exists()
            logger.info("Contextual learning enabled, history file initialized")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    logger.info(
        "Starting MassCode extension (pid=%d, python=%s, dir=%s)",
        os.getpid(),
        sys.version.split()[0],
        _EXT_DIR,
    )
    if not FUZZY_AVAILABLE:
        logger.warning("Dependency 'fuzzywuzzy' missing. Scoring features reduced.")
    try:
        MassCodeExtension().run()
    except Exception as main_err:
        logger.critical("Fatal error in extension: %s", main_err, exc_info=True)
        sys.exit(1)


# ==============================================================================
# END OF FILE/SCRIPT: masscode_extension.py
# ==============================================================================
