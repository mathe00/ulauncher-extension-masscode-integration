#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Handler Module

This module provides unified error handling, logging helpers,
and error message display functionality for the extension.
"""

import logging
from typing import Optional


logger = logging.getLogger(__name__)


def log_error(
    error: Exception,
    message: str = "",
    context: Optional[str] = None,
    exc_info: bool = True,
) -> None:
    """
    Log an error with optional context information.

    Args:
        error (Exception): The error exception
        message (str, optional): Additional message context
        context (str, optional): Context describing where the error occurred
        exc_info (bool, optional): Whether to include exception info. Defaults to True.
    """
    error_msg = f"{context}: {error}" if context else str(error)
    if message:
        error_msg = f"{message} - {error_msg}"
    logger.error(error_msg, exc_info=exc_info)


def log_warning(message: str) -> None:
    """
    Log a warning message.

    Args:
        message (str): The warning message
    """
    logger.warning(message)


def log_info(message: str) -> None:
    """
    Log an informational message.

    Args:
        message (str): The info message
    """
    logger.info(message)


def log_debug(message: str) -> None:
    """
    Log a debug message.

    Args:
        message (str): The debug message
    """
    logger.debug(message)
