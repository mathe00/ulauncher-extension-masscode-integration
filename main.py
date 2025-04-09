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
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
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
        """Update context-specific selection history"""
        # Check if contextual autocomplete is enabled
        if self.preferences.get('enable_contextual_autocomplete', 'true') != 'true':
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
            
            # Load context history only if feature is enabled
            context_history = extension.load_context_history() if contextual_enabled else {}
            
            # Find exact and similar queries in history (if feature enabled)
            relevant_contexts = self._find_relevant_contexts(query, context_history) if contextual_enabled else {}
            
            # Match snippets and sort with context awareness
            matches = self._get_matches_with_context(query, snippets, relevant_contexts)
            
            # Build result items
            items = self._create_result_items(matches, query, preferences)
            
            return RenderResultListAction(items)
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}")
            return self._show_error(f"Error: {str(e)}")

    def _find_relevant_contexts(self, query: str, 
                              context_history: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, float]]:
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

    def _get_matches_with_context(self, query: str, snippets: List[Dict], 
                                relevant_contexts: Dict[str, Dict[str, Any]]) -> List[Dict]:
        """Match snippets against query with context awareness"""
        matches = []
        normalized_query = query.lower().strip()
        
        snippet_context_score = {}  # Store context scores for each snippet
        
        # Calculate context scores for each snippet
        for context_query, context_data in relevant_contexts.items():
            context_relevance = context_data['relevance']
            for snippet_name, selection_count in context_data['snippets'].items():
                # Context score = (times selected) * (context relevance to current query)
                context_score = selection_count * context_relevance
                snippet_context_score[snippet_name] = max(
                    snippet_context_score.get(snippet_name, 0),
                    context_score
                )
        
        # Score and match all snippets
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
            title_score = 100 if normalized_query == "" else fuzz.partial_ratio(
                normalized_query, name.lower())
            content_score = 80 if normalized_query == "" else fuzz.partial_ratio(
                normalized_query, content_text.lower())
            
            # Combined score with title having more weight
            combined_score = (0.7 * title_score) + (0.3 * content_score)
            
            # Only include if score exceeds threshold or query is empty
            if combined_score > 50 or not normalized_query:
                # Get context score if this snippet has been selected before
                context_score = snippet_context_score.get(name, 0)
                
                # Add to matches
                matches.append({
                    'snippet': snippet,
                    'name': name,
                    'content': content_text,
                    'fuzzy_score': combined_score,
                    'context_score': context_score
                })
                
        # Sort matches
        return self._sort_matches(matches)

    def _sort_matches(self, matches: List[Dict]) -> List[Dict]:
        """Sort matches based on context scores and fuzzy scores"""
        # First, separate matches with context history vs. without
        context_matches = [m for m in matches if m['context_score'] > 0]
        regular_matches = [m for m in matches if m['context_score'] == 0]
        
        # Sort context matches by context score (and fuzzy score as tiebreaker)
        context_matches.sort(key=lambda x: (-x['context_score'], -x['fuzzy_score']))
        
        # Sort regular matches by fuzzy score
        regular_matches.sort(key=lambda x: -x['fuzzy_score'])
        
        # Return context matches followed by regular matches (limited to reasonable number)
        return (context_matches + regular_matches)[:8]  # Limit to 8 results total

    def _create_result_items(self, matches: List[Dict], query: str, 
                            preferences) -> List[ExtensionResultItem]:
        """Create ExtensionResultItem objects from matches"""
        items = []
        contextual_enabled = preferences.get('enable_contextual_autocomplete', 'true') == 'true'
        
        for match in matches:
            snippet = match['snippet']
            name = match['name']
            content_text = match['content']
            
            # Prepare data for tracking selection
            data = {
                'query': query,
                'snippet_name': name,
                'content': content_text,
                'has_context': match['context_score'] > 0
            }
            
            # Create action that will report selection to the extension
            action = ExtensionCustomAction(data, keep_app_open=False)
            
            # Format description - truncate if too long
            description = content_text.replace("\n", " ")
            if len(description) > 100:
                description = description[:97] + '...'
                
            # Add indicator if this is a contextual suggestion (only if enabled)
            if contextual_enabled and match['context_score'] > 0:
                name_prefix = "★ "  # Star to indicate contextual choice
            else:
                name_prefix = ""
            
            # Add item to results
            items.append(ExtensionResultItem(
                icon='images/icon.png',
                name=f"{name_prefix}{name}",
                description=description,
                on_enter=action
            ))
            
        # If no matches were found
        if not items:
            items.append(ExtensionResultItem(
                icon='images/icon.png',
                name='No matching snippets found',
                description='Try a different search term',
                on_enter=RenderResultListAction([])
            ))
            
        return items
    
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
        data = event.get_data()
        if not data:
            return RenderResultListAction([])
        
        try:
            # Extract data
            query = data.get('query', '')
            snippet_name = data.get('snippet_name', '')
            content = data.get('content', '')
            
            # Update context history only if query is not empty
            if query.strip():
                extension.update_context_history(query, snippet_name)
            
            # Copy content to clipboard and show confirmation
            return RenderResultListAction([
                ExtensionResultItem(
                    icon='images/icon.png',
                    name='Snippet copied: ' + snippet_name[:30],
                    description='Content copied to clipboard',
                    on_enter=CopyToClipboardAction(content)
                )
            ])
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