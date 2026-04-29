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
import importlib.util

# ==============================================================================
# SAFE LIBS LOADING — Prevent compiled .so conflicts with Ulauncher's runtime
# ==============================================================================
# Ulauncher adds the extension's root directory AND the libs/ subdirectory to
# sys.path. If libs/ contains compiled C extensions (like Levenshtein .so files)
# built for a different Python version, they crash the extension at import time
# because Ulauncher's own code imports the same modules transitively.
#
# Strategy: Insert ONLY the specific pure-Python packages we need from libs/,
# and ensure the libs/ directory itself is NOT at the front of sys.path where
# it could override system packages.
#
# This fixes: https://github.com/mathe00/ulauncher-extension-masscode-integration/issues/4
# ==============================================================================
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBS_DIR = os.path.join(_EXT_DIR, "libs")
_SRC_DIR = os.path.join(_EXT_DIR, "src")

# Add src/ to the front of sys.path for our module imports
sys.path.insert(0, _SRC_DIR)

# Ensure libs/ is in sys.path but AFTER system packages (low priority)
# This allows our pure-Python libs (fuzzywuzzy, pyyaml, pyperclip) to be found
# only if they're not already installed system-wide, while preventing compiled
# .so leftovers in libs/ from shadowing Ulauncher's system-installed packages.
if _LIBS_DIR in sys.path:
    sys.path.remove(_LIBS_DIR)
sys.path.append(_LIBS_DIR)

# Ulauncher API imports (must come after sys.path manipulation above)
from ulauncher.api.client.Extension import Extension  # noqa: E402
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent  # noqa: E402

# Imports from our modular architecture
from src.events.listeners import KeywordQueryEventListener, ItemEnterEventListener  # noqa: E402
from src.learning.contextual_history import ensure_history_file_exists  # noqa: E402

# Check if fuzzywuzzy is available (optional dependency)
FUZZY_AVAILABLE = importlib.util.find_spec("fuzzywuzzy") is not None

# --- Logging Configuration ---
try:
    from ulauncher.api.client.utils import get_logger

    logger = get_logger(__name__)
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    logger = logging.getLogger(__name__)


# ==============================================================================
# MAIN CLASS OF THE EXTENSION
# ==============================================================================
class MassCodeExtension(Extension):
    """
    Main extension class for MassCode snippet search.

    This class acts as a thin orchestrator that coordinates the various
    modules of the extension. The actual logic is delegated to:
    - libs/database.loader: Snippet loading from JSON/SQLite
    - libs.learning.contextual_history: Contextual learning and history
    - libs.events.listeners: Event handling for queries and selections
    - libs.utils.fuzzy_search: Fuzzy matching and relevance scoring
    - libs.results.builder: Result item construction
    - libs.fragments.fragment_utils: Multi-fragment handling
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
    logger.info("Starting the MassCode extension (Refactored Modular Architecture)")
    try:
        if not FUZZY_AVAILABLE:
            logger.warning("Dependency 'fuzzywuzzy' missing. Scoring features reduced.")
        MassCodeExtension().run()
    except Exception as main_err:
        logger.critical(f"Fatal error in extension: {main_err}", exc_info=True)
        sys.exit(1)


# ==============================================================================
# END OF FILE/SCRIPT: masscode_extension.py
# ==============================================================================
