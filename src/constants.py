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
MASSCODE_V5 = "v5"  # Markdown Vault (V5+)

# Markdown Vault internal constants (V5)
VAULT_META_DIR = ".masscode"  # Metadata directory inside vault
VAULT_STATE_FILE = "state.json"  # Central snippet index file

# Folder metadata file names
# MassCode migrated from .masscode-folder.yml to .meta.yaml
# We support both for backward compatibility
VAULT_FOLDER_META_FILE = ".meta.yaml"  # Current folder metadata file (massCode >= ~5.x)
VAULT_FOLDER_META_FILE_LEGACY = ".masscode-folder.yml"  # Legacy folder metadata file

# Vault "spaces" — massCode organizes vaults into sections (spaces)
# Each space (code/, notes/, math/) has its own .masscode/state.json
# The "code" space contains snippets, "notes" contains notes
VAULT_CODE_SPACE = "code"
VAULT_NOTES_SPACE = "notes"
VAULT_MATH_SPACE = "math"
VAULT_KNOWN_SPACES = [VAULT_CODE_SPACE, VAULT_NOTES_SPACE, VAULT_MATH_SPACE]

# Default preferences
DEFAULT_DB_PATH_V3 = "~/massCode/db.json"
DEFAULT_DB_PATH_V4 = "~/massCode/massCode.db"
DEFAULT_DB_PATH_V5 = "~/massCode/markdown-vault"
DEFAULT_SMART_RATIO_THRESHOLD = 0.0
DEFAULT_CONTEXTUAL_LEARNING = True
DEFAULT_QUERY_DEBOUNCE = 0.05

# Save-new-snippet feature constants
SAVE_SUBCOMMAND = "new"  # Sub-command to trigger save mode (e.g., "ms new")
DEFAULT_SNIPPET_LANGUAGE = "plain_text"  # Default language for saved snippets
CLIPBOARD_PREVIEW_MAX_LEN = 100  # Max chars shown in Ulauncher description
SNIPPET_NAME_MAX_LEN = 50  # Max chars for auto-generated snippet name
