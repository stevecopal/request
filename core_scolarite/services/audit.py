"""
Journal d'audit — enregistrement des opérations administratives.

Chaque écriture de la console (création, modification, suppression, import,
export, publication, émission d'accès) passe par `record()` : acteur, adresse
IP, université et détail des changements sont tracés dans `AuditLog`
(journal immuable côté modèle).
"""

from __future__ import annotations

from core_scolarite.models import AuditLog

__all__ = ["client_ip", "record", "diff_changes"]


def client_ip(request) -> str | None:
    """Adresse IP du client (X-Forwarded-For prioritaire derrière un proxy)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def record(request, action: str, **kwargs) -> AuditLog:
    """Trace une opération administrative liée à la requête courante."""
    kwargs.setdefault(
        "actor", request.user if getattr(request.user, "is_authenticated", False) else None
    )
    kwargs.setdefault("ip", client_ip(request))
    return AuditLog.record(action=action, **kwargs)


def diff_changes(instance, cleaned_data: dict) -> dict:
    """Champ → {avant, après} pour les champs réellement modifiés."""
    changes = {}
    for field, value in cleaned_data.items():
        try:
            before = getattr(instance, field)
        except (AttributeError, ValueError):
            continue
        if hasattr(before, "pk"):
            before = str(before.pk)
        if hasattr(value, "pk"):
            value = str(value.pk)
        if before != value:
            changes[field] = {"from": str(before) if before is not None else None,
                              "to": str(value) if value is not None else None}
    return changes
