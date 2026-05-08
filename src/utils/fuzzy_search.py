#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fuzzy Search Module

This module provides functions for fuzzy string matching and relevance scoring.
It handles searching for similar queries and calculating fuzzy scores for snippet matching.
"""

import logging
from typing import Dict, Any

try:
    from fuzzywuzzy import fuzz

    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Track whether we already warned about fuzzywuzzy being missing
# (avoid spamming the log on every search query)
_fuzzy_missing_warned = False


def calculate_fuzzy_score(
    query: str,
    searchable_name: str,
    content_text: str = "",
) -> int:
    """
    Calculate fuzzy matching score for a snippet.

    Args:
        query (str): The search query
        searchable_name (str): The name (or name with fragment label) to match against
        content_text (str, optional): The content text to also match against

    Returns:
        int: Combined fuzzy score (0-100), or 0 if fuzzywuzzy is unavailable

    Note:
        Uses a weighted combination of name matching (70%) and content matching (30%)
        When fuzzywuzzy is unavailable, falls back to simple substring matching.
    """
    if not query:
        return 100  # Show all results when no query is provided

    if FUZZY_AVAILABLE:
        title_score = fuzz.partial_ratio(query.lower(), searchable_name.lower())
        content_score = (
            fuzz.partial_ratio(query.lower(), content_text.lower())
            if content_text
            else 0
        )
        combined_score = (0.7 * title_score) + (0.3 * content_score)
        return int(combined_score)

    # Fallback: simple substring matching when fuzzywuzzy is unavailable
    global _fuzzy_missing_warned
    if not _fuzzy_missing_warned:
        logger.warning(
            "fuzzywuzzy not available — using basic substring search. "
            "Install with: pip install fuzzywuzzy -t libs/"
        )
        _fuzzy_missing_warned = True

    query_lower = query.lower()
    if query_lower in searchable_name.lower() or (
        content_text and query_lower in content_text.lower()
    ):
        return 51  # Just above the threshold (50) to pass the filter
    return 0


def find_relevant_contexts(
    query: str, context_history: Dict[str, Dict[str, int]]
) -> Dict[str, Dict[str, Any]]:
    """
    Find relevant historical contexts for a given query.

    This method searches through the context history to find similar queries
    that may help inform fuzzy matching results.

    Args:
        query (str): The current search query
        context_history (Dict[str, Dict[str, int]]): The loaded context history

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping query strings to their relevance
                                    and associated snippet selection data

    Note:
        Relevance is calculated based on exact matches, prefix matches,
        and fuzzy similarity ratios using fuzzywuzzy if available.
    """
    normalized_query = query.lower().strip()
    if not normalized_query:
        return {}
    relevant_contexts = {}

    for hist_query, snippets_data in context_history.items():
        relevance = calculate_relevance(normalized_query, hist_query)

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


def calculate_relevance(normalized_query: str, hist_query: str) -> float:
    """
    Calculate relevance score between two queries.

    Scoring tiers:
      - Exact match: 1.0
      - Query is prefix of history: 0.9 * length ratio
      - History is prefix of query: 0.8 * length ratio
      - Fuzzy similarity > 85% (requires fuzzywuzzy): 0.7 * ratio
      - Otherwise: 0.0 (no relevance)

    Args:
        normalized_query (str): The normalized current query
        hist_query (str): The historical query to compare against

    Returns:
        float: Relevance score (0.0 to 1.0), indicating how similar the queries are
    """
    if hist_query == normalized_query:
        return 1.0

    if len(normalized_query) > 2 and hist_query.startswith(normalized_query):
        return (len(normalized_query) / len(hist_query)) * 0.9

    if len(hist_query) > 2 and normalized_query.startswith(hist_query):
        return (len(hist_query) / len(normalized_query)) * 0.8

    if len(normalized_query) > 3 and len(hist_query) > 3 and FUZZY_AVAILABLE:
        ratio = fuzz.ratio(normalized_query, hist_query)
        if ratio > 85:
            return (ratio / 100) * 0.7

    return 0.0


def get_context_score(
    snippet_name: str,
    relevant_contexts: Dict[str, Dict[str, Any]],
) -> int:
    """
    Get contextual learning score for a snippet.

    Args:
        snippet_name (str): The name of the snippet
        relevant_contexts (Dict[str, Dict[str, Any]]): Relevant contexts from history

    Returns:
        int: Context score indicating how often this snippet was selected
    """
    context_score = 0
    for context_data in relevant_contexts.values():
        if snippet_name in context_data["snippets"]:
            score = (
                context_data["snippets"][snippet_name] * context_data["relevance"] * 100
            )
            context_score = max(context_score, int(score))

    return context_score
