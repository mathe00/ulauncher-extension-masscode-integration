#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contextual Learning Module

This module provides functionality for tracking user selections
and enabling contextual autocomplete that learns from usage patterns.
It manages the context history file and provides methods for
loading, saving, and updating history data.
"""

import json
import logging
import os
from typing import Dict

from ..constants import HISTORY_FILE, MAX_HISTORY_QUERIES


logger = logging.getLogger(__name__)


def ensure_history_file_exists(history_file_path: str = HISTORY_FILE) -> None:
    """
    Ensure the history file exists by creating an empty one if needed.

    Args:
        history_file_path (str, optional): Path to the history file. Defaults to HISTORY_FILE.
    """
    if not os.path.exists(history_file_path):
        logger.info(f"Creating history file: {history_file_path}")
        try:
            save_context_history(history_data={}, history_file_path=history_file_path)
        except Exception as e:
            logger.error(f"Unable to create history file: {e}", exc_info=True)


def load_context_history(
    history_file_path: str = HISTORY_FILE,
) -> Dict[str, Dict[str, int]]:
    """
    Load the context history from file.

    Args:
        history_file_path (str, optional): Path to the history file. Defaults to HISTORY_FILE.

    Returns:
        Dict[str, Dict[str, int]]: The loaded history data mapping queries to snippets and their selection counts.
                                     Returns empty dict if file doesn't exist or is corrupted.
    """
    if not os.path.exists(history_file_path):
        return {}
    try:
        with open(history_file_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        logger.debug(f"History loaded ({len(history)} queries).")
        return history
    except json.JSONDecodeError:
        logger.warning(
            f"Invalid history JSON '{history_file_path}'. Resetting.",
            exc_info=True,
        )
        try:
            save_context_history(history_data={}, history_file_path=history_file_path)
        except Exception as save_e:
            logger.error(f"Unable to reset corrupted history: {save_e}", exc_info=True)
        return {}
    except Exception as e:
        logger.error(f"Error loading history: {e}", exc_info=True)
        return {}


def save_context_history(
    history_data: Dict[str, Dict[str, int]],
    history_file_path: str = HISTORY_FILE,
) -> None:
    """
    Save the context history to file.

    Args:
        history_data (Dict[str, Dict[str, int]]): History data to save
        history_file_path (str, optional): Path to the history file. Defaults to HISTORY_FILE.
    """
    logger.debug(f"Saving history ({len(history_data)} queries) to {history_file_path}")
    try:
        with open(history_file_path, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving history: {e}", exc_info=True)


def update_context_history(
    query: str,
    snippet_name: str,
    fragment_label: str = "",
    enable_contextual_learning: bool = True,
    history_file_path: str = HISTORY_FILE,
) -> None:
    """
    Update contextual learning history with user selection.

    This method tracks which snippets are selected for which queries,
    enabling the smart autocomplete to learn from usage patterns.

    Args:
        query (str): The search query used by the user
        snippet_name (str): The name of the snippet selected
        fragment_label (str, optional): The fragment label if selecting a specific fragment
        enable_contextual_learning (bool): Whether contextual learning is enabled in preferences
        history_file_path (str, optional): Path to the history file. Defaults to HISTORY_FILE.

    Note:
        History keys are formatted as "snippet_name" for single-fragment snippets or
        "snippet_name [fragment_label]" for fragment-level selections.
    """
    if not enable_contextual_learning:
        logger.debug("Contextual learning disabled, history not updated.")
        return

    history = load_context_history(history_file_path=history_file_path)
    normalized_query = query.lower().strip()
    if not normalized_query or not snippet_name:
        logger.warning("Attempting to update history with empty query or snippet name.")
        return

    # Create the history key
    # Note: snippet_name already includes fragment label if present (e.g., "poulet [Fragment 1]")
    # We use it directly without adding fragment_label again
    history_key = snippet_name

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

    save_context_history(history_data=history, history_file_path=history_file_path)
