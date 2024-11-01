#!/usr/bin/env python3
import os
import sys

# Add libs folder to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'libs'))

import json
import logging
import subprocess
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.BaseAction import BaseAction
from fuzzywuzzy import fuzz

# Path to history file
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'history.json')

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MassCodeExtension(Extension):
    def __init__(self):
        super(MassCodeExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())

    def load_snippets(self, db_path):
        """Load snippets from db.json file"""
        try:
            with open(db_path, 'r') as f:
                data = json.load(f)
            return [snippet for snippet in data.get("snippets", []) if not snippet.get("isDeleted", False)]
        except Exception as e:
            logger.error("Error loading snippets from db.json: %s", e)
            return []

    def load_history(self):
        """Load selection history from history.json file"""
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_history(self, history):
        """Save selection history to history.json file"""
        try:
            with open(HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            logger.error("Error saving selection history: %s", e)

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        query = event.get_argument() or ""
        preferences = extension.preferences
        db_path = os.path.expanduser(preferences['mc_db_path'])
        snippets = extension.load_snippets(db_path)
        history = extension.load_history()

        # History for this specific query
        query_history = history.get(query, {})

        # Build a list of results based on history and fuzzy scores
        matches = []

        for snippet in snippets:
            name = snippet.get('name', '')
            content = snippet.get('content', '')

            if isinstance(content, list):
                content_text = "\n".join(fragment.get('value', '') for fragment in content)
            else:
                content_text = content

            title_score = fuzz.partial_ratio(query.lower(), name.lower())
            content_score = fuzz.partial_ratio(query.lower(), content_text.lower())
            combined_score = (0.8 * title_score) + (0.2 * content_score)

            if combined_score > 50:
                matches.append({
                    'snippet': snippet,
                    'score': combined_score,
                    'history_count': query_history.get(name, 0)  # Number of selections for this query
                })

        # Sort: first by number of selections for this query, then by similarity score
        matches.sort(key=lambda x: (-x['history_count'], -x['score']))

        items = []
        copy_paste_mode = preferences.get('copy_paste_mode', 'copy')

        for match in matches[:5]:  # Limit to 5 results
            snippet = match['snippet']
            content_text = "\n".join(fragment.get('value', '') for fragment in snippet['content']) if isinstance(snippet['content'], list) else snippet['content']

            # Define action based on mode
            action = CopyToClipboardAction(content_text)  # Simply copy the content

            # Add item to results
            items.append(ExtensionResultItem(
                icon='images/icon.png',
                name=snippet['name'],
                description=content_text[:100] + '...' if len(content_text) > 100 else content_text,
                on_enter=action
            ))

        return RenderResultListAction(items)

class ItemEnterEventListener(EventListener):
    def on_event(self, event, extension):
        data = event.get_data()
        if not data:
            return RenderResultListAction([])

        # Extract data for history update
        query = data.get('query')
        snippet_name = data.get('snippet_name')

        # Update history
        history = extension.load_history()
        if query not in history:
            history[query] = {}
        if snippet_name not in history[query]:
            history[query][snippet_name] = 0
        history[query][snippet_name] += 1  # Increment counter
        extension.save_history(history)

        # Display action result
        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name='Snippet copied',
                description='Content copied to clipboard',
                on_enter=CopyToClipboardAction(data.get('content', ''))
            )
        ])

if __name__ == '__main__':
    MassCodeExtension().run()
