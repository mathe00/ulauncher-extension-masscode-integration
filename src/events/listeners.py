#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Event Listeners Module

This module provides event listeners for handling Ulauncher extension events:
- KeywordQueryEvent: Search queries and result display
- ItemEnterEvent: Item selection and history recording
"""

import logging
import os
from typing import List

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

from ..database.loader import load_snippets, is_json_file, is_sqlite_file
from ..learning.contextual_history import load_context_history, update_context_history
from ..utils.fuzzy_search import (
    find_relevant_contexts,
    calculate_fuzzy_score,
    get_context_score,
)
from ..results.builder import create_error_message, create_result_items
from ..constants import FUZZY_SCORE_THRESHOLD, MAX_RESULTS


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
                    "Set db.json path.",
                    "images/icon-warning.png",
                )

            # Load snippets
            masscode_version = preferences.get("masscode_version", "v3")
            snippets = load_snippets(db_path=db_path, masscode_version=masscode_version)
            if not snippets:
                expanded_path = os.path.expanduser(db_path) if db_path else ""

                # Detect file type for better error messages
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

                # Default error messages based on version
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

    def _match_snippets(
        self,
        snippets: List[dict],
        query: str,
        relevant_contexts: dict,
        contextual_learning_enabled: bool,
    ) -> List[dict]:
        """
        Match snippets against query using fuzzy matching and context scoring.
        """
        matches = []
        for snippet in snippets:
            name = snippet.get("name", "Unnamed")
            content_data = snippet.get("content", "")
            content_text = (
                content_data if isinstance(content_data, str) else str(content_data)
            )

            # Calculate fuzzy score
            combined_score = calculate_fuzzy_score(
                query=query,
                searchable_name=name,
                content_text=content_text,
            )

            # Calculate context score (simple lookup by name)
            context_score = 0
            if contextual_learning_enabled and relevant_contexts:
                for context_data in relevant_contexts.values():
                    if name in context_data["snippets"]:
                        score = (
                            context_data["snippets"][name]
                            * context_data["relevance"]
                            * 100
                        )
                        context_score = max(context_score, int(score))

            # Add match if score meets threshold or no query
            if combined_score >= FUZZY_SCORE_THRESHOLD or not query:
                matches.append(
                    {
                        "name": name,
                        "content": content_text,
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
    """Event listener for handling item selection events (history recording)."""

    def on_event(self, event: ItemEnterEvent, extension) -> None:
        """
        Handle item enter event.

        Records the user's selection to the context history for learning.

        Args:
            event (ItemEnterEvent): The item selection event
            extension: The MassCodeExtension instance
        """
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

            if query is None or snippet_name is None:
                logger.error(
                    "Missing data ('query' or 'snippet_name') for history update."
                )
                return

            update_context_history(
                query=query,
                snippet_name=snippet_name,
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
        return None
