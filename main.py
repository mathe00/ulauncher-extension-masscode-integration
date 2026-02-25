#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# START OF FILE/SCRIPT: masscode_extension.py
# DESCRIPTION: ULauncher extension for searching and copying snippets
#              from MassCode, with optional contextual learning and
#              smart single result display.
# ==============================================================================

import os
import sys
import json
import logging
import sqlite3
import time
from typing import List, Dict, Any, Union, Optional, Tuple

# Add the 'libs' folder to PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), "libs"))

# Ulauncher API imports
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.ActionList import ActionList

# Import for fuzzy matching
try:
    from fuzzywuzzy import fuzz
except ImportError:
    print(
        "ERROR: The 'fuzzywuzzy' library is required but was not found.",
        file=sys.stderr,
    )

# --- Constants ---
EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(EXTENSION_DIR, "context_history.json")
MAX_HISTORY_QUERIES = 100
FUZZY_SCORE_THRESHOLD = 50
MAX_RESULTS = 8

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
    def __init__(self):
        logger.info("Initializing MassCodeExtension")
        super(MassCodeExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

        if self.preferences.get("enable_contextual_learning") == "true":
            self._ensure_history_file_exists()

    def _ensure_history_file_exists(self) -> None:
        if not os.path.exists(HISTORY_FILE):
            logger.info(f"Creating history file: {HISTORY_FILE}")
            try:
                self.save_context_history(history_data={})
            except Exception as e:
                logger.error(f"Unable to create history file: {e}", exc_info=True)

    def load_snippets(self, db_path: str) -> List[Dict[str, Any]]:
        """
        Load snippets from MassCode database based on version preference.

        This method routes to the appropriate loader based on the user's MassCode version
        preference. For V3 and earlier, it uses JSON format. For V4+, it uses SQLite.

        Args:
            db_path (str): Path to the MassCode database file (db.json for V3, massCode.db for V4+)

        Returns:
            List[Dict[str, Any]]: List of snippet dictionaries in the format expected by the search logic

        Note:
            The return format is normalized to match the existing JSON structure for seamless
            compatibility with the rest of the extension's search and display logic.
            Multi-fragment snippets are expanded into separate entries for fragment-level selection.
        """
        masscode_version = self.preferences.get("masscode_version", "v3")

        if masscode_version == "v4":
            raw_snippets = self.load_snippets_sqlite(db_path)
        else:
            raw_snippets = self.load_snippets_json(db_path)

        # Expand multi-fragment snippets into separate selectable entries
        expanded_snippets = []
        for snippet in raw_snippets:
            # Check if this snippet has multiple fragments (content is list with multiple items)
            content = snippet.get("content")
            has_multiple_fragments = snippet.get("_multi_fragment", False) or (
                isinstance(content, list) and content
            )

            if has_multiple_fragments:
                # Expand this snippet's fragments into separate entries
                expanded = self._expand_snippet_fragments(snippet)
                expanded_snippets.extend(expanded)
            else:
                # Single fragment snippet - add as-is
                expanded_snippets.append(snippet)

        logger.info(
            f"Loaded {len(raw_snippets)} snippets, expanded to {len(expanded_snippets)} fragments."
        )
        return expanded_snippets

    def _expand_snippet_fragments(
        self, snippet: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Expand a snippet with multiple fragments into separate entries for display.

        This helper function handles the transformation of multi-fragment snippets into
        individual searchable entries, preserving fragment labels and enabling selective
        copying of specific fragments.

        Args:
            snippet (Dict[str, Any]): A snippet dictionary potentially containing multiple fragments

        Returns:
            List[Dict[str, Any]]: A list of snippet dictionaries, one per fragment (or the original if single fragment)

        Note:
            Each fragment becomes its own entry with '_fragment_label' and '_fragment_content'
            fields added to indicate which specific fragment content should be copied.
        """
        content = snippet.get("content", "")

        # If content is not a list, it's a single fragment or empty content - return as-is
        if not isinstance(content, list):
            return [snippet]

        # Check if we actually have multiple fragments
        # Return original if only one or zero fragment (to avoid unnecessary processing)
        if len(content) <= 1:
            return [snippet]

        # Multiple fragments detected - expand into separate entries
        expanded_snippets = []
        base_metadata = {
            k: v
            for k, v in snippet.items()
            if k
            not in ["content", "name"]  # Preserve metadata, exclude content and name
        }

        for fragment in content:
            fragment_label = fragment.get("label", "")
            fragment_value = fragment.get("value", "")
            fragment_lang = fragment.get("language", "plaintext")

            # Handle empty fragments - still show them but mark as empty
            if not fragment_value:
                fragment_value = "[Empty Fragment]"  # Marker for empty content

            # Create standalone entry for this fragment
            fragment_snippet = {
                "name": snippet.get("name", "Unnamed"),
                "content": fragment_value,  # Only this fragment's content
                "_fragment_label": fragment_label,  # Label for display name (e.g., "[Connection]")
                "_fragment_language": fragment_lang,  # Language info
                "_fragment_index": content.index(fragment),  # Position for ordering
                **base_metadata,  # Copy all other metadata
            }

            expanded_snippets.append(fragment_snippet)

        # In case something went wrong and we got nothing, return original
        if not expanded_snippets:
            return [snippet]

        return expanded_snippets

    def load_snippets_json(self, db_path: str) -> List[Dict[str, Any]]:
        """
        Load snippets from MassCode V3 JSON format.

        This is the original loader for JSON-based databases used in MassCode V3 and earlier.
        Maintains backward compatibility with existing installations.

        Args:
            db_path (str): Path to the MassCode JSON database file (typically db.json)

        Returns:
            List[Dict[str, Any]]: List of snippet dictionaries in V3 format

        Raises:
            FileNotFoundError: When the specified JSON file doesn't exist
            json.JSONDecodeError: When the JSON file is malformed
        """
        expanded_path = os.path.expanduser(db_path)
        logger.debug(f"Loading snippets from JSON: {expanded_path}")

        # Check if file exists
        if not os.path.exists(expanded_path):
            logger.error(f"JSON DB file not found: {expanded_path}")
            return []

        # Check if it's actually a SQLite file (wrong version selected)
        if self._is_sqlite_file(expanded_path):
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

    def load_snippets_sqlite(self, db_path: str) -> List[Dict[str, Any]]:
        """
        Load snippets from MassCode V4+ SQLite database.

        This loader handles the new SQLite-based database format introduced in MassCode V4+.
        It performs the necessary JOIN operations to reconstruct snippet data in a format
        compatible with the existing search logic.

        Args:
            db_path (str): Path to the MassCode SQLite database file (typically massCode.db)

        Returns:
            List[Dict[str, Any]]: List of snippet dictionaries normalized to V3 format for compatibility

        Raises:
            sqlite3.Error: When there are database connectivity or query issues
            FileNotFoundError: When the specified database file doesn't exist

        Note:
            The method transforms the relational SQLite data into the flat structure expected
            by the existing search and display logic, ensuring seamless compatibility.
            For multi-fragment snippets, fragments are preserved with their labels for display
            as separate selectable entries.
        """
        expanded_path = os.path.expanduser(db_path)
        logger.debug(f"Loading snippets from SQLite: {expanded_path}")

        # Validate database file exists
        if not os.path.exists(expanded_path):
            logger.error(f"SQLite DB file not found: {expanded_path}")
            return []

        # Check if it's actually a JSON file (wrong version selected)
        if self._is_json_file(expanded_path):
            logger.warning(f"File appears to be JSON but V4+ selected: {expanded_path}")
            return []

        try:
            with sqlite3.connect(expanded_path) as conn:
                # Enable row factory for named access
                conn.row_factory = sqlite3.Row

                # Query to get all active snippets with their content fragments
                # Joins folders, snippets, and snippet_contents tables
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
                        # Create new snippet entry
                        snippets_dict[snippet_id] = {
                            "id": snippet_id,
                            "name": row["name"] or "Unnamed",
                            "description": row["description"],
                            "folderId": row["folderId"],
                            "isDeleted": bool(row["isDeleted"]),
                            "isFavorites": bool(row["isFavorites"]),
                            "createdAt": row["createdAt"],
                            "updatedAt": row["updatedAt"],
                            "folder_name": row["folder_name"],
                            "content": [],  # Will hold content fragments
                        }

                    # Add content fragment if it exists
                    if row["content_value"]:
                        snippets_dict[snippet_id]["content"].append(
                            {
                                "label": row["content_label"] or "",
                                "value": row["content_value"],
                                "language": row["language"] or "plaintext",
                            }
                        )

                # Convert to list format and preserve fragment structure
                snippets = []
                for snippet_data in snippets_dict.values():
                    content = snippet_data["content"]

                    if not content:
                        # No content fragments - create single entry with empty content
                        snippet = {
                            "name": snippet_data["name"],
                            "content": "",
                            "isDeleted": snippet_data["isDeleted"],
                            "_fragments_content": [],  # Empty list
                        }
                    elif len(content) == 1:
                        # Single fragment - use as string for backward compatibility
                        fragment = content[0]
                        snippet = {
                            "name": snippet_data["name"],
                            "content": fragment["value"],
                            "isDeleted": snippet_data["isDeleted"],
                            "_fragments_content": [
                                fragment["value"]
                            ],  # Store single fragment
                            "_fragment_label": fragment["label"]
                            or "",  # Store label for reference
                        }
                    else:
                        # Multiple fragments - preserve full structure for fragment-level handling
                        # Create separate entries for accessibility while keeping metadata
                        base_snippet = {
                            "name": snippet_data["name"],
                            "content": content,  # Keep as list for fragment handling
                            "isDeleted": snippet_data["isDeleted"],
                            "_multi_fragment": True,  # Flag for multi-fragment snippets
                        }
                        snippets.append(base_snippet)
                        continue  # Skip the rest of this iteration

                    # Add V4-specific metadata as extensions for future use
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
            logger.error(
                f"Unexpected error loading SQLite snippets: {e}", exc_info=True
            )
            return []

    def _is_sqlite_file(self, file_path: str) -> bool:
        """
        Check if a file is a SQLite database by reading the first few bytes.

        SQLite files start with the magic bytes "SQLite format 3\000".

        Args:
            file_path (str): Path to the file to check

        Returns:
            bool: True if the file appears to be a SQLite database, False otherwise
        """
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
                # SQLite format 3 magic bytes
                return header.startswith(b"SQLite format 3")
        except (IOError, OSError):
            return False

    def _is_json_file(self, file_path: str) -> bool:
        """
        Check if a file is a JSON file by reading the first few bytes.

        JSON files typically start with '{' or '['.

        Args:
            file_path (str): Path to the file to check

        Returns:
            bool: True if the file appears to be a JSON file, False otherwise
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                first_char = f.read(1)
                return first_char in ["{", "["]
        except (IOError, OSError, UnicodeDecodeError):
            return False

    def load_context_history(self) -> Dict[str, Dict[str, int]]:
        if not os.path.exists(HISTORY_FILE):
            return {}
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            logger.debug(f"History loaded ({len(history)} queries).")
            return history
        except json.JSONDecodeError:
            logger.warning(
                f"Invalid history JSON '{HISTORY_FILE}'. Resetting.",
                exc_info=True,
            )
            try:
                self.save_context_history(history_data={})
            except Exception as save_e:
                logger.error(
                    f"Unable to reset corrupted history: {save_e}",
                    exc_info=True,
                )
            return {}
        except Exception as e:
            logger.error(f"Error loading history: {e}", exc_info=True)
            return {}

    def save_context_history(self, history_data: Dict[str, Dict[str, int]]) -> None:
        logger.debug(f"Saving history ({len(history_data)} queries) to {HISTORY_FILE}")
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving history: {e}", exc_info=True)

    def update_context_history(
        self, query: str, snippet_name: str, fragment_label: str = ""
    ) -> None:
        """
        Update contextual learning history with user selection.

        Args:
            query (str): The search query used by the user
            snippet_name (str): The name of the snippet selected
            fragment_label (str, optional): The fragment label if selecting a specific fragment

        Note:
            History keys are formatted as "snippet_name" for single-fragment snippets or
            "snippet_name [fragment_label]" for fragment-level selections.
        """
        if self.preferences.get("enable_contextual_learning") != "true":
            logger.debug("Contextual learning disabled, history not updated.")
            return

        history = self.load_context_history()
        normalized_query = query.lower().strip()
        if not normalized_query or not snippet_name:
            logger.warning(
                "Attempting to update history with empty query or snippet name."
            )
            return

        # Create the history key: include fragment label if present
        history_key = snippet_name
        if fragment_label:
            history_key = f"{snippet_name} [{fragment_label}]"

        logger.info(
            f"Updating History: Query='{normalized_query}', Snippet='{history_key}'"
        )
        if normalized_query not in history:
            history[normalized_query] = {}
        history[normalized_query][history_key] = (
            history[normalized_query].get(history_key, 0) + 1
        )

        if len(history) > MAX_HISTORY_QUERIES:
            logger.info(f"Pruning history (limit {MAX_HISTORY_QUERIES}).")
            keys_to_del = list(history.keys())[:-MAX_HISTORY_QUERIES]
            for k in keys_to_del:
                del history[k]

        self.save_context_history(history_data=history)


# ==============================================================================
# EVENT LISTENER: KEYWORD QUERY (KeywordQueryEvent)
# ==============================================================================
class KeywordQueryEventListener(EventListener):
    def on_event(
        self, event: KeywordQueryEvent, extension: MassCodeExtension
    ) -> RenderResultListAction:
        try:
            query = event.get_argument() or ""
            logger.info(f"Query received: '{query}'")
            preferences = extension.preferences
            db_path = preferences.get("mc_db_path")
            contextual_learning_enabled = (
                preferences.get("enable_contextual_learning") == "true"
            )
            smart_ratio_str = preferences.get("smart_single_result_ratio", "0.0")

            try:
                smart_ratio_threshold = float(smart_ratio_str)
                if not (0.0 <= smart_ratio_threshold <= 1.0):
                    logger.warning(
                        f"Invalid smart_single_result_ratio '{smart_ratio_str}' (must be 0.0-1.0). Disabling feature."
                    )
                    smart_ratio_threshold = 0.0
            except ValueError:
                logger.warning(
                    f"Could not parse smart_single_result_ratio '{smart_ratio_str}'. Disabling feature."
                )
                smart_ratio_threshold = 0.0

            if not db_path:
                return self._show_message(
                    "Configuration required",
                    "Set db.json path.",
                    "images/icon-warning.png",
                )

            snippets = extension.load_snippets(db_path=db_path)
            if not snippets:
                masscode_version = extension.preferences.get("masscode_version", "v3")
                expanded_path = os.path.expanduser(db_path) if db_path else ""

                # Detect file type for better error messages
                if expanded_path and os.path.exists(expanded_path):
                    if masscode_version == "v4" and self._is_json_file(expanded_path):
                        return self._show_message(
                            "Version Mismatch Error",
                            f"You selected V4+ but the file appears to be JSON format. Try selecting 'V3 or earlier' instead.",
                            "images/icon-warning.png",
                        )
                    elif masscode_version != "v4" and self._is_sqlite_file(
                        expanded_path
                    ):
                        return self._show_message(
                            "Version Mismatch Error",
                            f"You selected V3/earlier but the file appears to be SQLite format. Try selecting 'V4+' instead.",
                            "images/icon-warning.png",
                        )

                # Default error messages based on version
                if masscode_version == "v4":
                    expected_path = db_path or "~/massCode/massCode.db"
                    return self._show_message(
                        "SQLite Database Error",
                        f"Check that '{os.path.expanduser(expected_path)}' exists and MassCode V4+ is installed.",
                        "images/icon-error.png",
                    )
                else:
                    expected_path = db_path or "~/massCode/db.json"
                    return self._show_message(
                        "JSON Database Error",
                        f"Check that '{os.path.expanduser(expected_path)}' exists and MassCode V3 or earlier is installed.",
                        "images/icon-error.png",
                    )

            context_history = {}
            relevant_contexts = {}
            if contextual_learning_enabled:
                context_history = extension.load_context_history()
                if context_history:
                    relevant_contexts = self._find_relevant_contexts(
                        query=query, context_history=context_history
                    )

            matches = []
            for snippet in snippets:
                name = snippet.get("name", "Unnamed")
                fragment_label = snippet.get("_fragment_label", "")
                content_data = snippet.get("content", "")
                content_text = (
                    content_data if isinstance(content_data, str) else str(content_data)
                )

                # Build searchable text: name + fragment label (if present)
                searchable_name = name
                if fragment_label:
                    searchable_name = f"{name} {fragment_label}"

                title_score, content_score, combined_score = 0, 0, 0
                try:
                    if not query:
                        combined_score = 100  # Show all if no query
                    else:
                        title_score = fuzz.partial_ratio(
                            query.lower(), searchable_name.lower()
                        )
                        content_score = (
                            fuzz.partial_ratio(query.lower(), content_text.lower())
                            if content_text
                            else 0
                        )
                        combined_score = (0.7 * title_score) + (0.3 * content_score)
                except NameError:  # fuzzywuzzy missing
                    if (
                        not query
                        or query.lower() in searchable_name.lower()
                        or (content_text and query.lower() in content_text.lower())
                    ):
                        combined_score = 51  # Above threshold
                    logger.warning("fuzzywuzzy not available, simple search used.")

                context_score = 0
                if contextual_learning_enabled and relevant_contexts:
                    for context_query, context_data in relevant_contexts.items():
                        # Check if either the snippet name or snippet name with fragment label exists in history
                        snippet_key = name
                        if fragment_label:
                            snippet_key = f"{name} [{fragment_label}]"

                        if snippet_key in context_data["snippets"]:
                            context_score = max(
                                context_score,
                                context_data["snippets"][snippet_key]
                                * context_data["relevance"]
                                * 100,
                            )

                if combined_score >= FUZZY_SCORE_THRESHOLD or not query:
                    matches.append(
                        {
                            "name": name,
                            "content": content_text,
                            "fuzzy_score": combined_score,
                            "context_score": context_score,
                        }
                    )

            matches.sort(
                key=lambda x: (x["context_score"], x["fuzzy_score"]),
                reverse=True,
            )

            # --- Smart Single Result Feature ---
            normalized_query_for_history = query.lower().strip()
            if (
                contextual_learning_enabled
                and smart_ratio_threshold > 0.0
                and normalized_query_for_history in context_history
                and matches  # Only proceed if there are matches to filter
            ):
                query_specific_history = context_history[normalized_query_for_history]
                total_selections_for_query = sum(query_specific_history.values())

                if total_selections_for_query > 0:
                    for match_item in list(matches):  # Iterate copy for safe removal
                        snippet_name_in_match = match_item["name"]
                        fragment_label_in_match = match_item.get("_fragment_label", "")

                        # Build the history key for this match
                        history_key = snippet_name_in_match
                        if fragment_label_in_match:
                            history_key = (
                                f"{snippet_name_in_match} [{fragment_label_in_match}]"
                            )

                        if history_key in query_specific_history:
                            snippet_selection_count = query_specific_history[
                                history_key
                            ]
                            selection_ratio = (
                                snippet_selection_count / total_selections_for_query
                            )

                            logger.debug(
                                f"Smart Single Result Check: Snippet='{history_key}', "
                                f"Query='{normalized_query_for_history}', "
                                f"Count={snippet_selection_count}, Total={total_selections_for_query}, "
                                f"Ratio={selection_ratio:.2f}, Threshold={smart_ratio_threshold:.2f}"
                            )

                            if selection_ratio >= smart_ratio_threshold:
                                logger.info(
                                    f"Smart Single Result triggered for snippet '{history_key}' "
                                    f"with ratio {selection_ratio:.2f} >= {smart_ratio_threshold:.2f}. "
                                    f"Showing only this result."
                                )
                                matches = [match_item]  # Keep only this one
                                break  # Found dominant, stop checking others
            # --- End of Smart Single Result Feature ---

            items: List[ExtensionResultItem] = []
            for match in matches[:MAX_RESULTS]:
                snippet_name = match["name"]
                fragment_label = match.get("_fragment_label", "")
                content_text = match["content"]
                prefix = (
                    "★ "
                    if contextual_learning_enabled and match["context_score"] > 0
                    else ""
                )
                description = content_text.replace("\n", " ").strip()
                description = (
                    (description[:97] + "...")
                    if len(description) > 100
                    else description or "Empty snippet"
                )

                # Build display name with fragment label if present
                # Format: "Snippet Name [Fragment Label]" or just "Snippet Name"
                display_name = snippet_name
                if fragment_label:
                    display_name = f"{snippet_name} [{fragment_label}]"

                copy_action = CopyToClipboardAction(text=content_text)
                history_action_data = {
                    "action": "record_history",
                    "query": query,
                    "snippet_name": snippet_name,
                    "fragment_label": fragment_label,  # Include fragment label in history
                }
                history_trigger_action = ExtensionCustomAction(
                    data=history_action_data, keep_app_open=False
                )
                combined_action = ActionList([copy_action, history_trigger_action])

                items.append(
                    ExtensionResultItem(
                        icon=extension.preferences.get("icon", "images/icon.png"),
                        name=f"{prefix}{display_name}",
                        description=description,
                        on_enter=combined_action,
                    )
                )

            if not items:
                return self._show_message(
                    "No results",
                    f"No snippet found for '{query}'",
                    "images/icon.png",
                )

            logger.debug(f"Displaying {len(items)} results.")
            return RenderResultListAction(items)

        except NameError as ne:
            logger.error(f"fuzzywuzzy error: {ne}", exc_info=True)
            return self._show_message(
                "Library Error",
                "'fuzzywuzzy' missing?",
                "images/icon-error.png",
            )
        except Exception as e:
            logger.error(
                f"Error processing query '{event.get_argument()}': {e}",
                exc_info=True,
            )
            return self._show_message(
                "Internal Error",
                "Check Ulauncher logs.",
                "images/icon-error.png",
            )

    def _find_relevant_contexts(
        self, query: str, context_history: Dict[str, Dict[str, int]]
    ) -> Dict[str, Dict[str, Any]]:
        normalized_query = query.lower().strip()
        if not normalized_query:
            return {}
        relevant_contexts = {}
        for hist_query, snippets_data in context_history.items():
            relevance = 0.0
            try:
                if hist_query == normalized_query:
                    relevance = 1.0
                elif len(normalized_query) > 2 and hist_query.startswith(
                    normalized_query
                ):
                    relevance = (len(normalized_query) / len(hist_query)) * 0.9
                elif len(hist_query) > 2 and normalized_query.startswith(hist_query):
                    relevance = (len(hist_query) / len(normalized_query)) * 0.8
                elif len(normalized_query) > 3 and len(hist_query) > 3:
                    ratio = fuzz.ratio(normalized_query, hist_query)
                    if ratio > 85:
                        relevance = (ratio / 100) * 0.7
            except NameError:
                pass  # Ignore fuzzy if not available

            if relevance > 0:
                if (
                    hist_query not in relevant_contexts
                    or relevance > relevant_contexts[hist_query]["relevance"]
                ):
                    relevant_contexts[hist_query] = {
                        "snippets": snippets_data,
                        "relevance": relevance,
                    }
        return relevant_contexts

    def _show_message(
        self, title: str, message: str, icon: str = "images/icon.png"
    ) -> RenderResultListAction:
        return RenderResultListAction(
            [
                ExtensionResultItem(
                    icon=icon,
                    name=title,
                    description=message,
                    on_enter=HideWindowAction(),
                )
            ]
        )


# ==============================================================================
# EVENT LISTENER: ITEM SELECTION (ItemEnterEvent) - FOR HISTORY ONLY
# ==============================================================================
class ItemEnterEventListener(EventListener):
    def on_event(self, event: ItemEnterEvent, extension: MassCodeExtension) -> None:
        data = event.get_data()
        logger.debug(f"ItemEnterEvent received for history. Data: {data}")

        if not isinstance(data, dict) or data.get("action") != "record_history":
            logger.warning(
                "ItemEnterEvent received with invalid data/action for history."
            )
            return

        try:
            query = data.get("query")
            snippet_name = data.get("snippet_name")
            fragment_label = data.get("fragment_label", "")

            if query is None or snippet_name is None:
                logger.error(
                    "Missing data ('query' or 'snippet_name') for history update."
                )
                return

            extension.update_context_history(
                query=query, snippet_name=snippet_name, fragment_label=fragment_label
            )
            logger.debug("History update (triggered by ItemEnterEvent) completed.")

        except Exception as e:
            logger.error(
                f"Error during history update via ItemEnterEvent: {e}",
                exc_info=True,
            )
        return None


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting the MassCode extension")
    try:
        if "fuzz" not in globals():
            logger.warning("Dependency 'fuzzywuzzy' missing. Scoring features reduced.")
        MassCodeExtension().run()
    except Exception as main_err:
        logger.critical(f"Fatal error in extension: {main_err}", exc_info=True)
        sys.exit(1)

# ==============================================================================
# END OF FILE/SCRIPT: masscode_extension.py
# ==============================================================================
