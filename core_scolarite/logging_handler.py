"""
Handler de journalisation → table `TechnicalEvent` (C6).

Les erreurs remontées par Django (`django.request`, vues, signaux, tâches)
sont persistées afin d'être consultables dans la console
« Sécurité & audit → Erreurs & incidents ».

Règles :
  * seuls les enregistrements ERROR/CRITICAL sont écrits ;
  * **aucune exception n'est propagée** (un logger ne fait jamais échouer une
    requête) — garde anti-récursion incluse (une erreur d'écriture ne doit
    pas re-déclencher le handler) ;
  * aucun secret ni donnée personnelle ajouté : seul le message du journal
    et sa trace d'exception sont conservés.
"""

from __future__ import annotations

import logging
import threading
import traceback as traceback_module

_local = threading.local()

MAX_MESSAGE = 4000
MAX_TRACEBACK = 12000

__all__ = ["DatabaseLogHandler"]


class DatabaseLogHandler(logging.Handler):
    """Écrit les erreurs/CRITICAL dans `core_scolarite.TechnicalEvent`."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        # Anti-récursion : une erreur survenue pendant l'écriture est ignorée.
        if getattr(_local, "emitting", False):
            return
        _local.emitting = True
        try:
            from core_scolarite.models import TechnicalEvent

            message = record.getMessage() or record.name
            traceback_text = ""
            if record.exc_info:
                traceback_text = "".join(
                    traceback_module.format_exception(*record.exc_info)
                )
            levelname = record.levelname
            if levelname not in TechnicalEvent.Level.values:
                levelname = TechnicalEvent.Level.ERROR
            TechnicalEvent.objects.create(
                level=levelname,
                source=TechnicalEvent.Source.SYSTEM,
                logger=(record.name or "")[:100],
                message=message[:MAX_MESSAGE],
                traceback=(traceback_text or "")[:MAX_TRACEBACK],
            )
        except Exception:  # noqa: BLE001 — un logger ne doit jamais lever.
            pass
        finally:
            _local.emitting = False
