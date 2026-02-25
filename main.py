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

# Add the 'src' folder to PYTHONPATH for our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Ulauncher API imports
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent

# Imports from our modular architecture
from src.events.listeners import KeywordQueryEventListener, ItemEnterEventListener
from src.learning.contextual_history import ensure_history_file_exists

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
