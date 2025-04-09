#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# -- FileMetadata-START --
# script_name="MassCode Ulauncher Extension"
# script_tags=["ulauncher", "masscode", "snippets", "productivity", "utility"]
# icon_path="images/icon.png"
# requires_permissions="false"
# -- FileMetadata-END --

# ==============================================================================
# DEBUT DU FICHIER/SCRIPT : masscode_extension.py
# DESCRIPTION: Extension ULauncher pour rechercher et copier des snippets
#              depuis MassCode, avec apprentissage contextuel optionnel.
# ==============================================================================

import os
import sys
import json
import logging
import time
from typing import List, Dict, Any, Union, Optional, Tuple

# Ajoute le dossier 'libs' au PYTHONPATH
sys.path.append(os.path.join(os.path.dirname(__file__), 'libs'))

# Importations Ulauncher API
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction # Importé pour clarté
from ulauncher.api.shared.action.ActionList import ActionList # IMPORTANT: Pour combiner des actions

# Importation pour la recherche floue
try:
    from fuzzywuzzy import fuzz
except ImportError:
    print("ERREUR: La bibliothèque 'fuzzywuzzy' est requise mais n'a pas été trouvée.", file=sys.stderr)

# --- Constantes ---
EXTENSION_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(EXTENSION_DIR, 'context_history.json')
MAX_HISTORY_QUERIES = 100
FUZZY_SCORE_THRESHOLD = 50
MAX_RESULTS = 8

# --- Configuration du Logging ---
try:
    from ulauncher.api.client.utils import get_logger
    logger = get_logger(__name__)
except ImportError:
    # Fallback si get_logger n'est pas dispo (anciennes versions Ulauncher?)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)]
    )
    logger = logging.getLogger(__name__)

# ==============================================================================
# CLASSE PRINCIPALE DE L'EXTENSION
# ==============================================================================
class MassCodeExtension(Extension):
    def __init__(self):
        logger.info("Initialisation de MassCodeExtension")
        super(MassCodeExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener()) # Gardé pour l'historique

        if self.preferences.get('activer_apprentissage_contextuel') == 'true':
            self._ensure_history_file_exists()

    def _ensure_history_file_exists(self) -> None:
        if not os.path.exists(HISTORY_FILE):
            logger.info(f"Création du fichier d'historique: {HISTORY_FILE}")
            try:
                self.save_context_history(history_data={})
            except Exception as e:
                logger.error(f"Impossible de créer le fichier d'historique: {e}", exc_info=True)

    def load_snippets(self, db_path: str) -> List[Dict[str, Any]]:
        expanded_path = os.path.expanduser(db_path)
        logger.debug(f"Chargement snippets depuis: {expanded_path}")
        try:
            with open(expanded_path, 'r', encoding='utf-8') as f: data = json.load(f)
            snippets = [s for s in data.get("snippets", []) if not s.get("isDeleted", False)]
            logger.info(f"{len(snippets)} snippets actifs chargés.")
            return snippets
        except FileNotFoundError: logger.error(f"Fichier DB introuvable: {expanded_path}"); return []
        except json.JSONDecodeError: logger.error(f"JSON invalide: {expanded_path}"); return []
        except Exception as e: logger.error(f"Erreur chargement snippets: {e}", exc_info=True); return []

    def load_context_history(self) -> Dict[str, Dict[str, int]]:
        if not os.path.exists(HISTORY_FILE): return {}
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: history = json.load(f)
            logger.debug(f"Historique chargé ({len(history)} requêtes).")
            return history
        except json.JSONDecodeError:
            logger.warning(f"JSON historique invalide '{HISTORY_FILE}'. Réinitialisation.", exc_info=True)
            try: self.save_context_history(history_data={})
            except Exception as save_e: logger.error(f"Impossible de réinitialiser historique corrompu: {save_e}", exc_info=True)
            return {}
        except Exception as e: logger.error(f"Erreur chargement historique: {e}", exc_info=True); return {}

    def save_context_history(self, history_data: Dict[str, Dict[str, int]]) -> None:
        logger.debug(f"Sauvegarde historique ({len(history_data)} requêtes) vers {HISTORY_FILE}")
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history_data, f, indent=4, ensure_ascii=False)
        except Exception as e: logger.error(f"Erreur sauvegarde historique: {e}", exc_info=True)

    def update_context_history(self, query: str, snippet_name: str) -> None:
        if self.preferences.get('activer_apprentissage_contextuel') != 'true':
            logger.debug("Apprentissage contextuel désactivé, historique non mis à jour.")
            return

        history = self.load_context_history()
        normalized_query = query.lower().strip()
        if not normalized_query or not snippet_name:
            logger.warning("Tentative MAJ historique avec requête ou nom de snippet vide.")
            return

        logger.info(f"MAJ Historique: Requête='{normalized_query}', Snippet='{snippet_name}'")
        if normalized_query not in history: history[normalized_query] = {}
        history[normalized_query][snippet_name] = history[normalized_query].get(snippet_name, 0) + 1

        # Élagage si nécessaire
        if len(history) > MAX_HISTORY_QUERIES:
            logger.info(f"Élagage historique (limite {MAX_HISTORY_QUERIES}).")
            keys_to_del = list(history.keys())[:-MAX_HISTORY_QUERIES]
            for k in keys_to_del: del history[k]

        self.save_context_history(history_data=history)

# ==============================================================================
# ÉCOUTEUR D'ÉVÉNEMENTS : REQUÊTE MOT-CLÉ (KeywordQueryEvent)
# ==============================================================================
class KeywordQueryEventListener(EventListener):
    def on_event(self, event: KeywordQueryEvent, extension: MassCodeExtension) -> RenderResultListAction:
        try:
            query = event.get_argument() or ""
            logger.info(f"Requête reçue: '{query}'")
            preferences = extension.preferences
            db_path = preferences.get('mc_db_path')
            contextual_learning_enabled = preferences.get('activer_apprentissage_contextuel') == 'true'

            if not db_path:
                return self._show_message("Configuration requise", "Définir chemin db.json.", 'images/icon-warning.png')

            snippets = extension.load_snippets(db_path=db_path)
            if not snippets:
                return self._show_message("Erreur chargement", "Vérifiez db.json.", 'images/icon-error.png')

            context_history = {}
            relevant_contexts = {}
            if contextual_learning_enabled:
                context_history = extension.load_context_history()
                if context_history:
                    relevant_contexts = self._find_relevant_contexts(query=query, context_history=context_history)

            matches = []
            for snippet in snippets:
                name = snippet.get('name', 'Sans nom')
                content_data = snippet.get('content', '')
                content_text = "\n".join(f.get('value', '') for f in content_data) if isinstance(content_data, list) else str(content_data)

                title_score, content_score, combined_score = 0, 0, 0
                try:
                    if not query: combined_score = 100 # Afficher tout si pas de query
                    else:
                        title_score = fuzz.partial_ratio(query.lower(), name.lower())
                        content_score = fuzz.partial_ratio(query.lower(), content_text.lower()) if content_text else 0
                        combined_score = (0.7 * title_score) + (0.3 * content_score)
                except NameError: # fuzzywuzzy manquant
                    if not query or query.lower() in name.lower() or (content_text and query.lower() in content_text.lower()):
                       combined_score = 51 # Au dessus du seuil
                    logger.warning("fuzzywuzzy non dispo, recherche simple.")

                context_score = 0
                if contextual_learning_enabled and relevant_contexts:
                    for context_query, context_data in relevant_contexts.items():
                        if name in context_data['snippets']:
                            context_score = max(context_score, context_data['snippets'][name] * context_data['relevance'] * 100)

                if combined_score >= FUZZY_SCORE_THRESHOLD or not query:
                    matches.append({'name': name, 'content': content_text, 'fuzzy_score': combined_score, 'context_score': context_score})

            matches.sort(key=lambda x: (x['context_score'], x['fuzzy_score']), reverse=True)

            items: List[ExtensionResultItem] = []
            for match in matches[:MAX_RESULTS]:
                snippet_name = match['name']
                content_text = match['content']
                prefix = "★ " if contextual_learning_enabled and match['context_score'] > 0 else ""
                description = content_text.replace("\n", " ").strip()
                description = (description[:97] + '...') if len(description) > 100 else description or "Snippet vide"

                # --- CHANGEMENT MAJEUR ICI ---
                # Action principale : Copier le contenu
                copy_action = CopyToClipboardAction(text=content_text)

                # Action secondaire : Envoyer données pour l'historique
                history_action_data = {
                    'action': 'record_history', # Nouvel identifiant
                    'query': query,
                    'snippet_name': snippet_name
                    # Pas besoin d'envoyer 'content' ici, on le copie déjà
                }
                history_trigger_action = ExtensionCustomAction(data=history_action_data, keep_app_open=False) # keep_app_open=False pour fermer après copie

                # Combinaison des actions: Copie D'ABORD, puis déclenchement de l'historique
                # Note: La fiabilité de ActionList peut varier. Test nécessaire.
                # Si ActionList ne fonctionne pas de manière fiable, on devra peut-être
                # abandonner la mise à jour de l'historique ou trouver une autre astuce.
                combined_action = ActionList([copy_action, history_trigger_action])
                # --- FIN CHANGEMENT MAJEUR ---

                items.append(ExtensionResultItem(
                    icon=extension.preferences.get('icon', 'images/icon.png'),
                    name=f"{prefix}{snippet_name}",
                    description=description,
                    on_enter=combined_action # Utilise l'ActionList
                ))

            if not items:
                 return self._show_message("Aucun résultat", f"Aucun snippet trouvé pour '{query}'", 'images/icon.png')

            logger.debug(f"Affichage de {len(items)} résultats.")
            return RenderResultListAction(items)

        except NameError as ne:
             logger.error(f"Erreur fuzzywuzzy: {ne}", exc_info=True)
             return self._show_message("Erreur Librairie", "'fuzzywuzzy' manquante?", 'images/icon-error.png')
        except Exception as e:
            logger.error(f"Erreur traitement requête '{event.get_argument()}': {e}", exc_info=True)
            return self._show_message("Erreur interne", "Vérifiez logs Ulauncher.", 'images/icon-error.png')

    def _find_relevant_contexts(self, query: str, context_history: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
        normalized_query = query.lower().strip()
        if not normalized_query: return {}
        relevant_contexts = {}
        for hist_query, snippets_data in context_history.items():
            relevance = 0.0
            try:
                if hist_query == normalized_query: relevance = 1.0
                elif len(normalized_query)>2 and hist_query.startswith(normalized_query): relevance = (len(normalized_query)/len(hist_query))*0.9
                elif len(hist_query)>2 and normalized_query.startswith(hist_query): relevance = (len(hist_query)/len(normalized_query))*0.8
                elif len(normalized_query)>3 and len(hist_query)>3:
                    ratio = fuzz.ratio(normalized_query, hist_query)
                    if ratio > 85: relevance = (ratio/100)*0.7
            except NameError: pass # Ignore fuzzy si non dispo

            if relevance > 0:
                if hist_query not in relevant_contexts or relevance > relevant_contexts[hist_query]['relevance']:
                   relevant_contexts[hist_query] = {'snippets': snippets_data, 'relevance': relevance}
        return relevant_contexts

    def _show_message(self, title: str, message: str, icon: str = 'images/icon.png') -> RenderResultListAction:
        return RenderResultListAction([
            ExtensionResultItem(icon=icon, name=title, description=message, on_enter=HideWindowAction())
        ])

# ==============================================================================
# ÉCOUTEUR D'ÉVÉNEMENTS : SÉLECTION D'ITEM (ItemEnterEvent) - POUR HISTORIQUE SEULEMENT
# ==============================================================================
class ItemEnterEventListener(EventListener):
    """
    Gère UNIQUEMENT la mise à jour de l'historique lorsque l'action
    personnalisée 'record_history' est déclenchée. Ne retourne AUCUNE action.
    """
    def on_event(self, event: ItemEnterEvent, extension: MassCodeExtension) -> None: # Modifié pour retourner None
        """
        Met à jour l'historique basé sur les données reçues.
        """
        data = event.get_data()
        logger.debug(f"ItemEnterEvent reçu pour historique. Données: {data}")

        # Vérifie si c'est bien l'action pour l'historique
        if not isinstance(data, dict) or data.get('action') != 'record_history':
            logger.warning("ItemEnterEvent reçu avec données/action invalides pour l'historique.")
            return # Ne rien faire d'autre

        try:
            query = data.get('query')
            snippet_name = data.get('snippet_name')

            if query is None or snippet_name is None:
                 logger.error("Données manquantes ('query' ou 'snippet_name') pour MAJ historique.")
                 return

            # Met à jour l'historique (la méthode gère l'activation/désactivation)
            extension.update_context_history(query=query, snippet_name=snippet_name)
            logger.debug("Mise à jour de l'historique (déclenchée par ItemEnterEvent) terminée.")

        except Exception as e:
            logger.error(f"Erreur lors MAJ historique via ItemEnterEvent: {e}", exc_info=True)

        # IMPORTANT: Ne retourne RIEN. L'action de copie a déjà été définie dans l'ActionList.
        return None

# ==============================================================================
# POINT D'ENTRÉE PRINCIPAL
# ==============================================================================
if __name__ == '__main__':
    logger.info("Démarrage de l'extension MassCode")
    try:
        if 'fuzz' not in globals():
             logger.warning("Dépendance 'fuzzywuzzy' manquante. Fonctionnalités de score réduites.")
        MassCodeExtension().run()
    except Exception as main_err:
        logger.critical(f"Erreur fatale extension: {main_err}", exc_info=True)
        sys.exit(1)

# ==============================================================================
# FIN DU FICHIER/SCRIPT : masscode_extension.py
# ==============================================================================