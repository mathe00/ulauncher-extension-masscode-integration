#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fragment Utilities Module

This module provides functionality for handling multi-fragment snippets,
expanding them into separate selectable entries for precise content selection.
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def expand_snippet_fragments(snippet: Dict[str, Any]) -> List[Dict[str, Any]]:
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
        if k not in ["content", "name"]  # Preserve metadata, exclude content and name
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
