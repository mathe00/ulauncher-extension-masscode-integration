"""
Contextual Learning Module

This module provides functionality for tracking user selections
and enabling contextual autocomplete that learns from usage patterns.
"""

from .contextual_history import (
    load_context_history,
    save_context_history,
    update_context_history,
    ensure_history_file_exists,
)

__all__ = [
    "load_context_history",
    "save_context_history",
    "update_context_history",
    "ensure_history_file_exists",
]
