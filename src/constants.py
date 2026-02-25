"""
Constants Module

This module defines shared constants used throughout the extension.
"""

import os

# Extension directory and file paths
# Go up one level from src/ to get extension root
EXTENSION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(EXTENSION_DIR, "context_history.json")

# Search and display thresholds
MAX_HISTORY_QUERIES = 100
FUZZY_SCORE_THRESHOLD = 50
MAX_RESULTS = 8

# MassCode version identifiers
MASSCODE_V3 = "v3"  # JSON-based (V3 and earlier)
MASSCODE_V4 = "v4"  # SQLite-based (V4 and later)

# Default preferences
DEFAULT_DB_PATH_V3 = "~/massCode/db.json"
DEFAULT_DB_PATH_V4 = "~/massCode/massCode.db"
DEFAULT_SMART_RATIO_THRESHOLD = 0.0
DEFAULT_CONTEXTUAL_LEARNING = True
DEFAULT_QUERY_DEBOUNCE = 0.05
