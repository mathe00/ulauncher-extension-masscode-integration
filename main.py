#!/usr/bin/env python3
import os
import sys
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
from fuzzywuzzy import fuzz, process

# History file to store user's selected snippets based on previous queries
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'history.json')

# Configure logging level
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class MassCodeExtension(Extension):
    def __init__(self):
        super(MassCodeExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())


class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        query = event.get_argument() or ""
        snippets_path = os.path.expanduser(extension.preferences['mc_db_path'])
        copy_paste_mode = extension.preferences['copy_paste_mode']
        items = []

        logger.debug(f"Query: {query}")
        logger.debug(f"Snippets Path: {snippets_path}")
        logger.debug(f"Copy Paste Mode: {copy_paste_mode}")

        try:
            with open(snippets_path, 'r') as file:
                data = json.load(file)
                all_snippets = data['snippets']
                
                snippet_strings = [
                    {
                        "id": snippet['id'],
                        "name": snippet['name'],
                        "content": ' '.join(content['value'] for content in snippet['content'])
                    } for snippet in all_snippets
                ]

                matches = self.get_ranked_matches(query, snippet_strings)

                for match in matches:
                    matched_snippet = match['snippet']
                    content_str = matched_snippet['content']
                    description = (content_str[:100] + '...') if len(content_str) > 100 else content_str
                    action = self.determine_action(copy_paste_mode, content_str)

                    items.append(ExtensionResultItem(
                        icon='images/icon.png',
                        name=self.wrap_text(self.highlight_match(matched_snippet['name'], query), 50),
                        description=description,
                        on_enter=action,
                        data={"query": query, "snippet_id": matched_snippet['id']}
                    ))

            return RenderResultListAction(items)

        except Exception as e:
            logger.error(f"Error during snippet search: {e}")
            return RenderResultListAction([
                ExtensionResultItem(icon='images/icon.png',
                                    name='Error',
                                    description='An error occurred. Check the logs.',
                                    on_enter=CopyToClipboardAction(''))
            ])

    def get_ranked_matches(self, query, snippets):
        """Returns snippets sorted by match score, using user's selection history."""
        query_lower = query.lower()
        history = self.load_history()

        # Retrieve fuzzy matches for the query
        fuzzy_matches = process.extract(query, [(snippet['name'] + ' ' + snippet['content']) for snippet in snippets], scorer=fuzz.token_sort_ratio, limit=10)

        # Link matched snippets to their IDs and fuzzy scores
        matches = []
        for text, score in fuzzy_matches:
            matched_snippet = next(snippet for snippet in snippets if snippet['name'] + ' ' + snippet['content'] == text)
            selection_count = history.get(query_lower, {}).get(matched_snippet['id'], 0)
            matches.append({"snippet": matched_snippet, "score": score + selection_count * 10})

        # Sort snippets based on fuzzy score combined with selection frequency
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

    def highlight_match(self, text, query):
        words = query.split()
        for word in words:
            text = text.replace(word, f"<b>{word}</b>")
        return text

    def wrap_text(self, text, width):
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= width:
                current_line += (word + " ")
            else:
                lines.append(current_line.strip())
                current_line = word + " "

        if current_line:
            lines.append(current_line.strip())

        return '\n'.join(lines)

    def determine_action(self, mode, content):
        if mode == 'copy':
            return CopyToClipboardAction(content)
        elif mode == 'paste':
            return BaseAction(lambda: subprocess.call("xdotool type --delay 1 '{}'".format(content.replace("'", "\\'")), shell=True))
        elif mode == 'both':
            def do_both():
                subprocess.call("echo '{}' | xclip -selection clipboard".format(content.replace("'", "\\'")), shell=True)
                subprocess.call("xdotool type --delay 1 '{}'".format(content.replace("'", "\\'")), shell=True)
            return BaseAction(do_both)

    def save_to_history(self, query, snippet_id):
        history = self.load_history()
        query_lower = query.lower()

        if query_lower not in history:
            history[query_lower] = {}
        if snippet_id not in history[query_lower]:
            history[query_lower][snippet_id] = 0
        history[query_lower][snippet_id] += 1

        with open(HISTORY_FILE, 'w') as history_file:
            json.dump(history, history_file)

    def load_history(self):
        if not os.path.exists(HISTORY_FILE):
            return {}
        with open(HISTORY_FILE, 'r') as history_file:
            return json.load(history_file)


class ItemEnterEventListener(EventListener):
    def on_event(self, event, extension):
        data = event.get_data()
        if not data:
            return RenderResultListAction([])

        query = data.get('query', '')
        snippet_id = data.get('snippet_id', '')
        snippet_content = data.get('content', '')

        KeywordQueryEventListener().save_to_history(query, snippet_id)

        return RenderResultListAction([
            ExtensionResultItem(icon='images/icon.png',
                                name='Snippet copied',
                                description='Content copied to clipboard',
                                on_enter=CopyToClipboardAction(snippet_content))
        ])


if __name__ == '__main__':
    MassCodeExtension().run()
