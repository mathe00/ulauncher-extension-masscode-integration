#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Results Builder Module

This module provides functionality for constructing extension result items
for display in Ulauncher, including formatting, styling, and action chaining.
"""

from typing import List, Dict, Any

from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.ActionList import ActionList


def create_error_message(
    title: str, message: str, icon: str = "images/icon.png"
) -> RenderResultListAction:
    """
    Create an error message result item.

    Args:
        title (str): The title of the error message
        message (str): The error message content
        icon (str, optional): Path to the icon to display. Defaults to "images/icon.png".

    Returns:
        RenderResultListAction: The action to render the error message
    """
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


def create_result_items(
    matches: List[Dict[str, Any]],
    icon: str,
    enable_contextual_learning: bool = False,
    max_results: int = 8,
) -> RenderResultListAction:
    """
    Create extension result items from matched snippets.

    Args:
        matches (List[Dict[str, Any]]): List of matched snippets with metadata
        icon (str): Path to the icon to display
        enable_contextual_learning (bool, optional): Whether contextual learning is enabled.
                                                    Defaults to False.
        max_results (int, optional): Maximum number of results to return. Defaults to 8.

    Returns:
        RenderResultListAction: The action to render the result list

    Note:
        Each result item includes copy-to-clipboard action and history recording action.
    """
    items: List[ExtensionResultItem] = []

    for match in matches[:max_results]:
        snippet_name = match.get("name", "")
        content_text = match.get("content", "")
        context_score = match.get("context_score", 0)

        # Add star prefix if contextual learning is enabled and this has context score
        prefix = "★ " if enable_contextual_learning and context_score > 0 else ""

        # Truncate description if too long
        description = content_text.replace("\n", " ").strip()
        description = (
            (description[:97] + "...")
            if len(description) > 100
            else description or "Empty snippet"
        )

        # Create actions
        copy_action = CopyToClipboardAction(text=content_text)
        history_action_data = {
            "action": "record_history",
            "query": match.get("query", ""),
            "snippet_name": snippet_name,
        }
        history_trigger_action = ExtensionCustomAction(
            data=history_action_data, keep_app_open=False
        )
        combined_action = ActionList([copy_action, history_trigger_action])

        # Create the result item
        items.append(
            ExtensionResultItem(
                icon=icon,
                name=f"{prefix}{snippet_name}",
                description=description,
                on_enter=combined_action,
            )
        )

    return RenderResultListAction(items)
