"""
Utility Function Modules

This package provides utility functions used across the extension.
"""

from .fuzzy_search import (
    find_relevant_contexts,
    calculate_fuzzy_score,
    get_context_score,
)
from .error_handler import log_error, log_warning, log_info, log_debug

__all__ = [
    "find_relevant_contexts",
    "calculate_fuzzy_score",
    "get_context_score",
    "log_error",
    "log_warning",
    "log_info",
    "log_debug",
]
