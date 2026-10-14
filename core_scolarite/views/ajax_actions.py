"""
Actions AJAX de core_scolarite.

Phase 5  : admin_actions.py — upload ETL (superuser only) → JSON.
Phase 6  : ajax_selectors.py — GET form-config (cascade du formulaire dynamique).
Phase 10 : analytics.py — agrégations Count / Case-When.

Note : les modules spécialisés sont créés dans leurs phases respectives ;
ce fichier documente le contrat commun (JSON, 403 hors droits, 404 ressource inconnue).
"""
