#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# START OF FILE/SCRIPT: masscode_extension.py
# DESCRIPTION: ULauncher extension for accessing MassCode snippets with contextual autocomplete
# ==============================================================================

import os
import sys

# Add libs folder to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'libs'))

import json
import logging
import time
from typing import List, Dict, Any, Union, Optional, Tuple
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from fuzzywuzzy import fuzz

# Paths
EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(EXTENSION_DIR, 'context_history.json')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MassCodeExtension(Extension):
    def __init__(self):
        super(MassCodeExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())
        
        # Ensure history file exists
        if not os.path.exists(HISTORY_FILE):
            self.save_context_history({})

    def load_snippets(self, db_path: str) -> List[Dict[str, Any]]:
        """Load snippets from db.json file"""
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Filter out deleted snippets
            return [snippet for snippet in data.get("snippets", []) 
                   if not snippet.get("isDeleted", False)]
        except FileNotFoundError:
            logger.error(f"Database file not found at: {db_path}")
            return []
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format in database file: {db_path}")
            return []
        except Exception as e:
            logger.error(f"Error loading snippets from db.json: {str(e)}")
            return []

    def load_context_history(self) -> Dict[str, Dict[str, int]]:
        """Load contextual selection history from history file"""
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info("History file not found, creating new")
            return {}
        except json.JSONDecodeError:
            logger.error("Invalid JSON in history file, resetting")
            return {}
        except Exception as e:
            logger.error(f"Error loading history: {str(e)}")
            return {}

    def save_context_history(self, history: Dict[str, Dict[str, int]]) -> None:
        """Save contextual selection history to file"""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving selection history: {str(e)}")
    
    def update_context_history(self, query: str, snippet_name: str) -> None:
        """Update context-specific selection history if enabled in preferences"""
        # Check if history and contextual autocomplete are enabled
        if (self.preferences.get('enable_history', 'true') != 'true' or 
            self.preferences.get('enable_contextual_autocomplete', 'true') != 'true'):
            return
        
        history = self.load_context_history()
        
        # Normalize query for consistency
        normalized_query = query.lower().strip()
        
        # Skip empty queries
        if not normalized_query:
            return
            
        if normalized_query not in history:
            history[normalized_query] = {}
            
        if snippet_name not in history[normalized_query]:
            history[normalized_query][snippet_name] = 0
            
        # Increment selection count for this specific query-snippet pair
        history[normalized_query][snippet_name] += 1
        
        # Prune history if it gets too large (keep only most recent 100 queries)
        if len(history) > 100:
            # Sort by timestamp if available, otherwise just take keys
            oldest_queries = sorted(list(history.keys()))[:len(history)-100]
            for old_query in oldest_queries:
                del history[old_query]
                
        self.save_context_history(history)

class KeywordQueryEventListener(EventListener):
    def on_event(self, event: KeywordQueryEvent, extension: MassCodeExtension):
        try:
            query = event.get_argument() or ""
            preferences = extension.preferences
            db_path = os.path.expanduser(preferences['mc_db_path'])
            
            # Load snippets
            snippets = extension.load_snippets(db_path)
            if not snippets:
                return self._show_error("No snippets found or database path is incorrect")
            
            # Check if contextual autocomplete is enabled
            contextual_enabled = preferences.get('enable_contextual_autocomplete', 'true') == 'true'
            history_enabled = preferences.get('enable_history', 'true') == 'true'
            
            # Load context history if enabled
            context_history = {}
            relevant_contexts = {}
            if contextual_enabled and history_enabled:
                context_history = extension.load_context_history()
                relevant_contexts = self._find_relevant_contexts(query, context_history)
            
            # Match snippets and sort with context awareness if enabled
            matches = []
            
            for snippet in snippets:
                name = snippet.get('name', '')
                content = snippet.get('content', '')

                # Extract text content
                if isinstance(content, list):
                    content_text = "\n".join(fragment.get('value', '') 
                                          for fragment in content)
                else:
                    content_text = content
                
                # Calculate fuzzy match scores
                title_score = 100 if not query else fuzz.partial_ratio(
                    query.lower(), name.lower())
                content_score = 80 if not query else fuzz.partial_ratio(
                    query.lower(), content_text.lower())
                
                # Combined score with title having more weight
                combined_score = (0.7 * title_score) + (0.3 * content_score)
                
                # Only include if score exceeds threshold or query is empty
                if combined_score > 50 or not query:
                    # Get context score if enabled
                    context_score = 0
                    if contextual_enabled and history_enabled:
                        # Check if this snippet has been selected before in relevant contexts
                        for context_query, context_data in relevant_contexts.items():
                            if name in context_data['snippets']:
                                # Context score = (times selected) * (context relevance)
                                selection_count = context_data['snippets'][name]
                                relevance = context_data['relevance']
                                context_score = max(context_score, selection_count * relevance)
                    
                    # Add to matches
                    matches.append({
                        'snippet': snippet,
                        'name': name,
                        'content': content_text,
                        'fuzzy_score': combined_score,
                        'context_score': context_score
                    })
            
            # Sort matches
            if contextual_enabled and history_enabled:
                # Sort by context score first, then fuzzy score
                matches.sort(key=lambda x: (-x['context_score'], -x['fuzzy_score']))
            else:
                # Sort just by fuzzy score
                matches.sort(key=lambda x: -x['fuzzy_score'])
            
            # Build result items
            items = []
            for match in matches[:8]:  # Limit to 8 results
                snippet = match['snippet']
                name = match['name']
                content_text = match['content']
                
                # Add star indicator for contextual matches
                prefix = "★ " if contextual_enabled and match['context_score'] > 0 else ""
                
                # Description: truncate if too long
                description = content_text.replace("\n", " ")
                if len(description) > 100:
                    description = description[:97] + '...'
                
                # Create direct CopyToClipboardAction
                items.append(ExtensionResultItem(
                    icon='images/icon.png',
                    name=f"{prefix}{name}",
                    description=description,
                    on_enter=CopyToClipboardAction(content_text)
                ))
            
            # If no matches were found
            if not items:
                items.append(ExtensionResultItem(
                    icon='images/icon.png',
                    name='No matching snippets found',
                    description='Try a different search term',
                    on_enter=RenderResultListAction([])
                ))
            
            return RenderResultListAction(items)
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            return self._show_error(f"Error: {str(e)}")
    
    def _find_relevant_contexts(self, query: str, 
                              context_history: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
        """Find exact and similar queries in history with their relevance scores"""
        normalized_query = query.lower().strip()
        if not normalized_query:
            return {}
            
        relevant_contexts = {}
        
        # Look for exact query match (highest priority)
        if normalized_query in context_history:
            relevant_contexts[normalized_query] = {
                'snippets': context_history[normalized_query],
                'relevance': 1.0  # Exact match gets full weight
            }
        
        # Check if query is a prefix of a historical query or vice versa
        for hist_query in context_history:
            # Skip exact matches (already handled)
            if hist_query == normalized_query:
                continue
                
            # Calculate string similarity
            if len(normalized_query) > 2 and len(hist_query) > 2:
                # If current query is prefix of historical query
                if hist_query.startswith(normalized_query):
                    prefix_ratio = len(normalized_query) / len(hist_query)
                    if prefix_ratio >= 0.7:  # Only consider if significant overlap
                        relevant_contexts[hist_query] = {
                            'snippets': context_history[hist_query],
                            'relevance': prefix_ratio * 0.9  # 90% of exact match importance
                        }
                # If historical query is prefix of current query
                elif normalized_query.startswith(hist_query):
                    prefix_ratio = len(hist_query) / len(normalized_query)
                    if prefix_ratio >= 0.7:  # Only consider if significant overlap
                        relevant_contexts[hist_query] = {
                            'snippets': context_history[hist_query],
                            'relevance': prefix_ratio * 0.8  # 80% of exact match importance
                        }
                # Check for high fuzzy match (for typos or slight variations)
                elif len(normalized_query) >= 4 and fuzz.ratio(normalized_query, hist_query) > 85:
                    relevant_contexts[hist_query] = {
                        'snippets': context_history[hist_query],
                        'relevance': 0.7  # 70% of exact match importance
                    }
        
        return relevant_contexts
                
    def _show_error(self, message: str) -> RenderResultListAction:
        """Show an error message in the results"""
        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name='Error',
                description=message,
                on_enter=RenderResultListAction([])
            )
        ])

class ItemEnterEventListener(EventListener):
    def on_event(self, event: ItemEnterEvent, extension: MassCodeExtension):
        try:
            data = event.get_data()
            if isinstance(data, str):
                # Handle direct string data (from CopyToClipboardAction)
                # Nothing to do here as CopyToClipboardAction handles the copying
                return
            
            # Handle dictionary data if we still have custom actions somewhere
            query = data.get('query', '') if data else ''
            snippet_name = data.get('snippet_name', '') if data else ''
            content = data.get('content', '') if data else ''
            
            # Update context history only if query is not empty
            if query.strip():
                extension.update_context_history(query, snippet_name)
                
            # Already copied by CopyToClipboardAction
            return RenderResultListAction([])
        except Exception as e:
            logger.error(f"Error processing item selection: {str(e)}")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon='images/icon.png',
                    name='Error copying snippet',
                    description=str(e),
                    on_enter=RenderResultListAction([])
                )
            ])

if __name__ == '__main__':
    MassCodeExtension().run()

# ==============================================================================
# END OF FILE/SCRIPT: masscode_extension.py
# ==============================================================================