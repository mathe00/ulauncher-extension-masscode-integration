#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Event Listeners Module

This module provides event listeners for handling Ulauncher extension events:
- KeywordQueryEvent: Search queries, result display, and save-new-snippet mode
- ItemEnterEvent: Item selection, history recording, and snippet saving
"""

import logging
import os
from typing import List

import pyperclip

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

from ..database.loader import (
    load_snippets,
    is_json_file,
    is_sqlite_file,
    is_markdown_vault,
)
from ..database.writer import save_snippet_to_inbox, generate_snippet_name
from ..learning.contextual_history import load_context_history, update_context_history
from ..utils.fuzzy_search import (
    find_relevant_contexts,
    calculate_fuzzy_score,
)
from ..results.builder import (
    create_error_message,
    create_result_items,
    create_save_result_item,
    create_save_confirmation_item,
)
from ..fragments.fragment_utils import expand_snippet_fragments
from ..constants import FUZZY_SCORE_THRESHOLD, MAX_RESULTS, SAVE_SUBCOMMAND


logger = logging.getLogger(__name__)


class KeywordQueryEventListener(EventListener):
    """Event listener for handling keyword query events (search queries)."""

    def on_event(self, event: KeywordQueryEvent, extension) -> RenderResultListAction:
        """
        Handle keyword query event.

        Processes search queries, loads snippets, performs fuzzy matching,
        applies contextual learning if enabled, and renders results.

        Args:
            event (KeywordQueryEvent): The query event
            extension: The MassCodeExtension instance

        Returns:
            RenderResultListAction: Action to render the search results
        """
        try:
            query = event.get_argument() or ""
            logger.info(f"Query received: '{query}'")

            # --- Save-new-snippet sub-command ---
            # Detect "new" sub-command: "ms new" or "ms new my snippet name"
            # Branch to save mode instead of search mode
            stripped_query = query.strip()
            if (
                stripped_query.lower() == SAVE_SUBCOMMAND
                or stripped_query.lower().startswith(SAVE_SUBCOMMAND + " ")
            ):
                return self._handle_save_mode(stripped_query, extension)

            # --- Existing: Search mode ---
            preferences = extension.preferences
            db_path = preferences.get("mc_db_path")
            contextual_learning_enabled = (
                preferences.get("enable_contextual_learning") == "true"
            )
            smart_ratio_str = preferences.get("smart_single_result_ratio", "0.0")

            # Parse smart ratio threshold
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

            # Validate database path is configured
            if not db_path:
                return create_error_message(
                    "Configuration required",
                    "Set MassCode DB path or vault directory.",
                    "images/icon-warning.png",
                )

            # Load snippets
            masscode_version = preferences.get("masscode_version", "v3")
            snippets = load_snippets(db_path=db_path, masscode_version=masscode_version)
            if not snippets:
                expanded_path = os.path.expanduser(db_path) if db_path else ""

                # V5-specific error handling
                if masscode_version == "v5":
                    if expanded_path and os.path.exists(expanded_path):
                        if os.path.isfile(expanded_path):
                            return create_error_message(
                                "Vault Path Error",
                                f"'{expanded_path}' is a file, not a directory. "
                                "For V5+, set the path to the markdown-vault/ folder.",
                                "images/icon-warning.png",
                            )
                        if not is_markdown_vault(expanded_path):
                            return create_error_message(
                                "Invalid Vault",
                                f"'{expanded_path}' doesn't look like a MassCode vault. "
                                "Missing '.masscode/state.json' (or 'code/.masscode/state.json').",
                                "images/icon-warning.png",
                            )
                    return create_error_message(
                        "Markdown Vault Error",
                        f"Check that '{os.path.expanduser(db_path or '~/massCode/markdown-vault')}' "
                        "exists and contains '.masscode/state.json' (or 'code/.masscode/state.json').",
                        "images/icon-error.png",
                    )

                # Detect file type for better error messages (V3/V4)
                if expanded_path and os.path.exists(expanded_path):
                    if masscode_version == "v4" and is_json_file(expanded_path):
                        return create_error_message(
                            "Version Mismatch Error",
                            "You selected V4+ but the file appears to be JSON format. Try selecting 'V3 or earlier' instead.",
                            "images/icon-warning.png",
                        )
                    elif masscode_version != "v4" and is_sqlite_file(expanded_path):
                        return create_error_message(
                            "Version Mismatch Error",
                            "You selected V3/earlier but the file appears to be SQLite format. Try selecting 'V4+' instead.",
                            "images/icon-warning.png",
                        )

                # Default error messages based on version (V3/V4)
                if masscode_version == "v4":
                    expected_path = db_path or "~/massCode/massCode.db"
                    return create_error_message(
                        "SQLite Database Error",
                        f"Check that '{os.path.expanduser(expected_path)}' exists and MassCode V4+ is installed.",
                        "images/icon-error.png",
                    )
                else:
                    expected_path = db_path or "~/massCode/db.json"
                    return create_error_message(
                        "JSON Database Error",
                        f"Check that '{os.path.expanduser(expected_path)}' exists and MassCode V3 or earlier is installed.",
                        "images/icon-error.png",
                    )

            # Load contextual history if enabled
            context_history = {}
            relevant_contexts = {}
            if contextual_learning_enabled:
                context_history = load_context_history()
                if context_history:
                    relevant_contexts = find_relevant_contexts(
                        query=query, context_history=context_history
                    )

            # Match snippets against query
            matches = self._match_snippets(
                snippets=snippets,
                query=query,
                relevant_contexts=relevant_contexts,
                contextual_learning_enabled=contextual_learning_enabled,
            )

            # Sort matches by context score then fuzzy score
            matches.sort(
                key=lambda x: (x.get("context_score", 0), x.get("fuzzy_score", 0)),
                reverse=True,
            )

            # Apply smart single result feature if enabled
            if (
                contextual_learning_enabled
                and smart_ratio_threshold > 0.0
                and query.lower().strip() in context_history
                and matches
            ):
                matches = self._apply_smart_single_result(
                    matches=matches,
                    query=query,
                    context_history=context_history,
                    smart_ratio_threshold=smart_ratio_threshold,
                )

            # Build result items
            icon = preferences.get("icon", "images/icon.png")
            if not matches:
                return create_error_message(
                    "No results",
                    f"No snippet found for '{query}'",
                    "images/icon.png",
                )

            return create_result_items(
                matches=matches,
                icon=icon,
                enable_contextual_learning=contextual_learning_enabled,
                max_results=MAX_RESULTS,
            )

        except NameError as ne:
            logger.error(f"fuzzywuzzy error: {ne}", exc_info=True)
            return create_error_message(
                "Library Error",
                "'fuzzywuzzy' missing?",
                "images/icon-error.png",
            )
        except Exception as e:
            logger.error(
                f"Error processing query '{event.get_argument()}': {e}",
                exc_info=True,
            )
            return create_error_message(
                "Internal Error",
                "Check Ulauncher logs.",
                "images/icon-error.png",
            )

    def _handle_save_mode(self, query: str, extension) -> RenderResultListAction:
        """
        Handle the 'new' sub-command to save clipboard content as a new snippet.

        UX flow:
          1. User types "ms new" → auto-generates name from clipboard first line
          2. User types "ms new my name" → uses "my name" as snippet name
          3. Shows preview of clipboard content as description
          4. On select: triggers save to MassCode Inbox

        Args:
            query: The full query string (e.g., "new my snippet name")
            extension: The MassCodeExtension instance

        Returns:
            RenderResultListAction with save preview result or error
        """
        preferences = extension.preferences
        db_path = preferences.get("mc_db_path")
        icon = preferences.get("icon", "images/icon.png")

        # Validate database path is configured
        if not db_path:
            return create_error_message(
                "Configuration required",
                "Set MassCode DB path or vault directory to save snippets.",
                "images/icon-warning.png",
            )

        # Read clipboard content
        try:
            clipboard_content = pyperclip.paste()
        except Exception as e:
            logger.error(f"Failed to read clipboard: {e}", exc_info=True)
            return create_error_message(
                "Clipboard Error",
                "Could not read clipboard content.",
                "images/icon-error.png",
            )

        # Check if clipboard has content
        if not clipboard_content or not clipboard_content.strip():
            return create_error_message(
                "Empty Clipboard",
                "Nothing to save — copy some text/code first, then try again.",
                "images/icon.png",
            )

        # Extract optional name from query: "new my snippet name" → "my snippet name"
        # "new" alone → None (will be auto-generated)
        remainder = query[len(SAVE_SUBCOMMAND) :].strip()
        snippet_name = remainder if remainder else None

        # Auto-generate name if not provided
        if not snippet_name:
            snippet_name = generate_snippet_name(clipboard_content)

        logger.info(
            f"Save mode: name='{snippet_name}', "
            f"clipboard_len={len(clipboard_content)}, "
            f"db_path='{db_path}'"
        )

        return create_save_result_item(
            name=snippet_name,
            clipboard_preview=clipboard_content,
            icon=icon,
        )

    def _match_snippets(
        self,
        snippets: List[dict],
        query: str,
        relevant_contexts: dict,
        contextual_learning_enabled: bool,
    ) -> List[dict]:
        """
        Match snippets against query using fuzzy matching and context scoring.
        Expands multi-fragment snippets into separate selectable entries.
        """
        matches = []

        # First, expand all snippets (multi-fragment snippets become multiple entries)
        expanded_snippets = []
        for snippet in snippets:
            expanded = expand_snippet_fragments(snippet)
            expanded_snippets.extend(expanded)

        for snippet in expanded_snippets:
            name = snippet.get("name", "Unnamed")
            fragment_label = snippet.get("_fragment_label", "")
            content_text = snippet.get("content", "")

            # Build display name: include fragment label if present
            # e.g., "poulet [Fragment 1]" instead of just "poulet"
            display_name = name
            if fragment_label:
                display_name = f"{name} [{fragment_label}]"

            # Calculate fuzzy score using the display name (includes fragment label)
            combined_score = calculate_fuzzy_score(
                query=query,
                searchable_name=display_name,
                content_text=content_text,
            )

            # Calculate context score using the display name (includes fragment label)
            # This allows learning per fragment: "poulet [Fragment 1]" vs "poulet [Fragment 2]"
            context_score = 0
            if contextual_learning_enabled and relevant_contexts:
                for context_data in relevant_contexts.values():
                    if display_name in context_data["snippets"]:
                        score = (
                            context_data["snippets"][display_name]
                            * context_data["relevance"]
                            * 100
                        )
                        context_score = max(context_score, int(score))

            # Add match if score meets threshold or no query
            if combined_score >= FUZZY_SCORE_THRESHOLD or not query:
                matches.append(
                    {
                        "name": display_name,  # Full name with fragment label
                        "content": content_text,
                        "fragment_label": fragment_label,  # Keep for history
                        "query": query,
                        "fuzzy_score": combined_score,
                        "context_score": context_score,
                    }
                )

        return matches

    def _apply_smart_single_result(
        self,
        matches: List[dict],
        query: str,
        context_history: dict,
        smart_ratio_threshold: float,
    ) -> List[dict]:
        """Apply smart single result filtering to matches."""
        normalized_query = query.lower().strip()
        query_specific_history = context_history[normalized_query]
        total_selections_for_query = sum(query_specific_history.values())

        if total_selections_for_query > 0:
            for match_item in matches:
                snippet_name = match_item.get("name")

                if snippet_name in query_specific_history:
                    snippet_selection_count = query_specific_history[snippet_name]
                    selection_ratio = (
                        snippet_selection_count / total_selections_for_query
                    )

                    if selection_ratio >= smart_ratio_threshold:
                        logger.info(
                            f"Smart Single Result: '{snippet_name}' "
                            f"ratio={selection_ratio:.2f} >= threshold={smart_ratio_threshold:.2f}"
                        )
                        return [match_item]

        return matches


class ItemEnterEventListener(EventListener):
    """Event listener for handling item selection events (history recording and snippet saving)."""

    def on_event(self, event: ItemEnterEvent, extension):
        """
        Handle item enter event.

        Dispatches to the appropriate handler based on the action type:
        - "record_history": Record snippet selection for contextual learning
        - "save_snippet": Save clipboard content as a new MassCode snippet

        Args:
            event (ItemEnterEvent): The item selection event
            extension: The MassCodeExtension instance

        Returns:
            RenderResultListAction for save confirmations, None for history recording
        """
        data = event.get_data()

        if not isinstance(data, dict):
            logger.warning("ItemEnterEvent received with invalid data (not a dict).")
            return None

        action = data.get("action")

        # Dispatch to the appropriate handler
        if action == "save_snippet":
            return self._handle_save_action(data, extension)
        elif action == "record_history":
            self._handle_history_action(data, extension)
            return None
        else:
            logger.warning(f"ItemEnterEvent received with unknown action: '{action}'")
            return None

    def _handle_save_action(self, data: dict, extension) -> RenderResultListAction:
        """
        Handle save_snippet action: save clipboard content to MassCode Inbox.

        Reads the snippet name from the action data, reads clipboard content,
        and calls the writer module to persist the snippet.

        Args:
            data: Action data dict with "name" key
            extension: The MassCodeExtension instance

        Returns:
            RenderResultListAction with success or error confirmation
        """
        try:
            name = data.get("name", "")
            preferences = extension.preferences
            db_path = preferences.get("mc_db_path")
            masscode_version = preferences.get("masscode_version", "v3")
            icon = preferences.get("icon", "images/icon.png")

            if not name:
                logger.error("Save action received without snippet name.")
                return create_save_confirmation_item(
                    name="unknown",
                    success=False,
                    error="No snippet name provided.",
                    icon=icon,
                )

            # Read clipboard content
            try:
                clipboard_content = pyperclip.paste()
            except Exception as e:
                logger.error(f"Failed to read clipboard for save: {e}", exc_info=True)
                return create_save_confirmation_item(
                    name=name,
                    success=False,
                    error=f"Could not read clipboard: {e}",
                    icon=icon,
                )

            if not clipboard_content or not clipboard_content.strip():
                return create_save_confirmation_item(
                    name=name,
                    success=False,
                    error="Clipboard is empty — nothing to save.",
                    icon=icon,
                )

            # Save to MassCode Inbox
            result = save_snippet_to_inbox(
                db_path=db_path,
                masscode_version=masscode_version,
                content=clipboard_content.strip(),
                name=name,
            )

            if result.get("success"):
                logger.info(f"Snippet saved successfully: {result}")
                return create_save_confirmation_item(
                    name=name,
                    success=True,
                    icon=icon,
                )
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"Snippet save failed: {error_msg}")
                return create_save_confirmation_item(
                    name=name,
                    success=False,
                    error=error_msg,
                    icon=icon,
                )

        except Exception as e:
            logger.error(f"Error during save action: {e}", exc_info=True)
            return create_save_confirmation_item(
                name=data.get("name", "unknown"),
                success=False,
                error=str(e),
                icon=preferences.get("icon", "images/icon.png")
                if extension
                else "images/icon.png",
            )

    def _handle_history_action(self, data: dict, extension) -> None:
        """
        Handle record_history action: update contextual learning history.

        Args:
            data: Action data dict with "query", "snippet_name", "fragment_label" keys
            extension: The MassCodeExtension instance
        """
        try:
            query = data.get("query")
            snippet_name = data.get("snippet_name")
            fragment_label = data.get("fragment_label", "")

            if query is None or snippet_name is None:
                logger.error(
                    "Missing data ('query' or 'snippet_name') for history update."
                )
                return

            update_context_history(
                query=query,
                snippet_name=snippet_name,
                fragment_label=fragment_label,
                enable_contextual_learning=extension.preferences.get(
                    "enable_contextual_learning"
                )
                == "true",
            )
            logger.debug("History update completed.")

        except Exception as e:
            logger.error(
                f"Error during history update via ItemEnterEvent: {e}",
                exc_info=True,
            )
