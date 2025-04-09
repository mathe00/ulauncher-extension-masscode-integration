#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# -- FileMetadata-START --
# script_name="MassCode Ulauncher Extension"
# script_tags=["ulauncher", "masscode", "snippets", "productivity", "utility"]
# icon_path="images/icon.png"
# requires_permissions="false"
# -- FileMetadata-END --

# ==============================================================================
# START OF FILE/SCRIPT: masscode_extension.py
# DESCRIPTION: ULauncher extension for searching and copying snippets
#              from MassCode, with optional contextual learning.
# ==============================================================================

import os
import sys
import json
import logging
import time
from typing import List, Dict, Any, Union, Optional, Tuple

# Add the 'libs' folder to PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), 'libs'))

# Ulauncher API imports
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction  # Imported for clarity
from ulauncher.api.shared.action.ActionList import ActionList  # IMPORTANT: For combining actions

# Import for fuzzy matching
try:
    from fuzzywuzzy import fuzz
except ImportError:
    print("ERROR: The 'fuzzywuzzy' library is required but was not found.", file=sys.stderr)

# --- Constants ---
EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(EXTENSION_DIR, 'context_history.json')
MAX_HISTORY_QUERIES = 100
FUZZY_SCORE_THRESHOLD = 50
MAX_RESULTS = 8

# --- Logging Configuration ---
try:
    from ulauncher.api.client.utils import get_logger
    logger = get_logger(__name__)
except ImportError:
    # Fallback if get_logger is not available (older versions of Ulauncher?)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)]
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
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())  # Kept for history

        if self.preferences.get('enable_contextual_learning') == 'true':
            self._ensure_history_file_exists()

    def _ensure_history_file_exists(self) -> None:
        if not os.path.exists(HISTORY_FILE):
            logger.info(f"Creating history file: {HISTORY_FILE}")
            try:
                self.save_context_history(history_data={})
            except Exception as e:
                logger.error(f"Unable to create history file: {e}", exc_info=True)

    def load_snippets(self, db_path: str) -> List[Dict[str, Any]]:
        expanded_path = os.path.expanduser(db_path)
        logger.debug(f"Loading snippets from: {expanded_path}")
        try:
            with open(expanded_path, 'r', encoding='utf-8') as f: data = json.load(f)
            snippets = [s for s in data.get("snippets", []) if not s.get("isDeleted", False)]
            logger.info(f"{len(snippets)} active snippets loaded.")
            return snippets
        except FileNotFoundError: logger.error(f"DB file not found: {expanded_path}"); return []
        except json.JSONDecodeError: logger.error(f"Invalid JSON: {expanded_path}"); return []
        except Exception as e: logger.error(f"Error loading snippets: {e}", exc_info=True); return []

    def load_context_history(self) -> Dict[str, Dict[str, int]]:
        if not os.path.exists(HISTORY_FILE): return {}
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: history = json.load(f)
            logger.debug(f"History loaded ({len(history)} queries).")
            return history
        except json.JSONDecodeError:
            logger.warning(f"Invalid history JSON '{HISTORY_FILE}'. Resetting.", exc_info=True)
            try: self.save_context_history(history_data={})
            except Exception as save_e: logger.error(f"Unable to reset corrupted history: {save_e}", exc_info=True)
            return {}
        except Exception as e: logger.error(f"Error loading history: {e}", exc_info=True); return {}

    def save_context_history(self, history_data: Dict[str, Dict[str, int]]) -> None:
        logger.debug(f"Saving history ({len(history_data)} queries) to {HISTORY_FILE}")
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history_data, f, indent=4, ensure_ascii=False)
        except Exception as e: logger.error(f"Error saving history: {e}", exc_info=True)

    def update_context_history(self, query: str, snippet_name: str) -> None:
        if self.preferences.get('enable_contextual_learning') != 'true':
            logger.debug("Contextual learning disabled, history not updated.")
            return

        history = self.load_context_history()
        normalized_query = query.lower().strip()
        if not normalized_query or not snippet_name:
            logger.warning("Attempting to update history with empty query or snippet name.")
            return

        logger.info(f"Updating History: Query='{normalized_query}', Snippet='{snippet_name}'")
        if normalized_query not in history: history[normalized_query] = {}
        history[normalized_query][snippet_name] = history[normalized_query].get(snippet_name, 0) + 1

        # Prune if necessary
        if len(history) > MAX_HISTORY_QUERIES:
            logger.info(f"Pruning history (limit {MAX_HISTORY_QUERIES}).")
            keys_to_del = list(history.keys())[:-MAX_HISTORY_QUERIES]
            for k in keys_to_del: del history[k]

        self.save_context_history(history_data=history)

# ==============================================================================
# EVENT LISTENER: KEYWORD QUERY (KeywordQueryEvent)
# ==============================================================================
class KeywordQueryEventListener(EventListener):
    def on_event(self, event: KeywordQueryEvent, extension: MassCodeExtension) -> RenderResultListAction:
        try:
            query = event.get_argument() or ""
            logger.info(f"Query received: '{query}'")
            preferences = extension.preferences
            db_path = preferences.get('mc_db_path')
            contextual_learning_enabled = preferences.get('enable_contextual_learning') == 'true'

            if not db_path:
                return self._show_message("Configuration required", "Set db.json path.", 'images/icon-warning.png')

            snippets = extension.load_snippets(db_path=db_path)
            if not snippets:
                return self._show_message("Loading error", "Check db.json.", 'images/icon-error.png')

            context_history = {}
            relevant_contexts = {}
            if contextual_learning_enabled:
                context_history = extension.load_context_history()
                if context_history:
                    relevant_contexts = self._find_relevant_contexts(query=query, context_history=context_history)

            matches = []
            for snippet in snippets:
                name = snippet.get('name', 'Unnamed')
                content_data = snippet.get('content', '')
                content_text = "\n".join(f.get('value', '') for f in content_data) if isinstance(content_data, list) else str(content_data)

                title_score, content_score, combined_score = 0, 0, 0
                try:
                    if not query: combined_score = 100  # Show all if no query
                    else:
                        title_score = fuzz.partial_ratio(query.lower(), name.lower())
                        content_score = fuzz.partial_ratio(query.lower(), content_text.lower()) if content_text else 0
                        combined_score = (0.7 * title_score) + (0.3 * content_score)
                except NameError:  # fuzzywuzzy missing
                    if not query or query.lower() in name.lower() or (content_text and query.lower() in content_text.lower()):
                       combined_score = 51  # Above threshold
                    logger.warning("fuzzywuzzy not available, simple search used.")

                context_score = 0
                if contextual_learning_enabled and relevant_contexts:
                    for context_query, context_data in relevant_contexts.items():
                        if name in context_data['snippets']:
                            context_score = max(context_score, context_data['snippets'][name] * context_data['relevance'] * 100)

                if combined_score >= FUZZY_SCORE_THRESHOLD or not query:
                    matches.append({'name': name, 'content': content_text, 'fuzzy_score': combined_score, 'context_score': context_score})

            matches.sort(key=lambda x: (x['context_score'], x['fuzzy_score']), reverse=True)

            items: List[ExtensionResultItem] = []
            for match in matches[:MAX_RESULTS]:
                snippet_name = match['name']
                content_text = match['content']
                prefix = "★ " if contextual_learning_enabled and match['context_score'] > 0 else ""
                description = content_text.replace("\n", " ").strip()
                description = (description[:97] + '...') if len(description) > 100 else description or "Empty snippet"

                # --- MAJOR CHANGE HERE ---
                # Main action: Copy content
                copy_action = CopyToClipboardAction(text=content_text)

                # Secondary action: Send data for history
                history_action_data = {
                    'action': 'record_history',  # New identifier
                    'query': query,
                    'snippet_name': snippet_name
                    # No need to send 'content' here, it is already copied
                }
                history_trigger_action = ExtensionCustomAction(data=history_action_data, keep_app_open=False)  # keep_app_open=False to close after copy

                # Combine actions: Copy FIRST, then trigger history update
                # Note: The reliability of ActionList may vary. Testing required.
                # If ActionList does not reliably work, it may be necessary to
                # forgo history updates or find another workaround.
                combined_action = ActionList([copy_action, history_trigger_action])
                # --- END OF MAJOR CHANGE ---

                items.append(ExtensionResultItem(
                    icon=extension.preferences.get('icon', 'images/icon.png'),
                    name=f"{prefix}{snippet_name}",
                    description=description,
                    on_enter=combined_action  # Uses ActionList
                ))

            if not items:
                 return self._show_message("No results", f"No snippet found for '{query}'", 'images/icon.png')

            logger.debug(f"Displaying {len(items)} results.")
            return RenderResultListAction(items)

        except NameError as ne:
             logger.error(f"fuzzywuzzy error: {ne}", exc_info=True)
             return self._show_message("Library Error", "'fuzzywuzzy' missing?", 'images/icon-error.png')
        except Exception as e:
            logger.error(f"Error processing query '{event.get_argument()}': {e}", exc_info=True)
            return self._show_message("Internal Error", "Check Ulauncher logs.", 'images/icon-error.png')

    def _find_relevant_contexts(self, query: str, context_history: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
        normalized_query = query.lower().strip()
        if not normalized_query: return {}
        relevant_contexts = {}
        for hist_query, snippets_data in context_history.items():
            relevance = 0.0
            try:
                if hist_query == normalized_query: relevance = 1.0
                elif len(normalized_query)>2 and hist_query.startswith(normalized_query): relevance = (len(normalized_query)/len(hist_query))*0.9
                elif len(hist_query)>2 and normalized_query.startswith(hist_query): relevance = (len(hist_query)/len(normalized_query))*0.8
                elif len(normalized_query)>3 and len(hist_query)>3:
                    ratio = fuzz.ratio(normalized_query, hist_query)
                    if ratio > 85: relevance = (ratio/100)*0.7
            except NameError: pass  # Ignore fuzzy if not available

            if relevance > 0:
                if hist_query not in relevant_contexts or relevance > relevant_contexts[hist_query]['relevance']:
                   relevant_contexts[hist_query] = {'snippets': snippets_data, 'relevance': relevance}
        return relevant_contexts

    def _show_message(self, title: str, message: str, icon: str = 'images/icon.png') -> RenderResultListAction:
        return RenderResultListAction([
            ExtensionResultItem(icon=icon, name=title, description=message, on_enter=HideWindowAction())
        ])

# ==============================================================================
# EVENT LISTENER: ITEM SELECTION (ItemEnterEvent) - FOR HISTORY ONLY
# ==============================================================================
class ItemEnterEventListener(EventListener):
    """
    Handles ONLY history updates when the action
    'record_history' is triggered. Does not return ANY action.
    """
    def on_event(self, event: ItemEnterEvent, extension: MassCodeExtension) -> None:  # Modified to return None
        """
        Updates history based on the received data.
        """
        data = event.get_data()
        logger.debug(f"ItemEnterEvent received for history. Data: {data}")

        # Check if it is the action for history
        if not isinstance(data, dict) or data.get('action') != 'record_history':
            logger.warning("ItemEnterEvent received with invalid data/action for history.")
            return  # Do nothing else

        try:
            query = data.get('query')
            snippet_name = data.get('snippet_name')

            if query is None or snippet_name is None:
                 logger.error("Missing data ('query' or 'snippet_name') for history update.")
                 return

            # Update the history (the method handles activation/deactivation)
            extension.update_context_history(query=query, snippet_name=snippet_name)
            logger.debug("History update (triggered by ItemEnterEvent) completed.")

        except Exception as e:
            logger.error(f"Error during history update via ItemEnterEvent: {e}", exc_info=True)

        # IMPORTANT: Return NOTHING. The copy action was already defined in the ActionList.
        return None

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == '__main__':
    logger.info("Starting the MassCode extension")
    try:
        if 'fuzz' not in globals():
             logger.warning("Dependency 'fuzzywuzzy' missing. Scoring features reduced.")
        MassCodeExtension().run()
    except Exception as main_err:
        logger.critical(f"Fatal error in extension: {main_err}", exc_info=True)
        sys.exit(1)

# ==============================================================================
# END OF FILE/SCRIPT: masscode_extension.py
# ==============================================================================