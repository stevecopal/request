"""
Indicateeurs de suivi des délais (C3 / C5) — seuils SLA, retards, blocages.

Deux niveaux de règle :
  * `policy_for(ticket)`  → règle **catégorie** (`SlaPolicy.problem_type`),
    à défaut règle **générale** de l'université (`problem_type` vide), à
    défaut défauts codés (5 j / 10 j) ;
  * `thresholds(...)`     → seuils lisibles pour un filtrage SQL (liste,
    tableau de bord, rapports).

Une requête est « en retard » au-delà de `max_days` et « bloquée » au-delà
de `blocked_after_days`, pour les statuts suivis par la règle.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core_scolarite.models import SlaPolicy

DEFAULT_MAX_DAYS = 5
DEFAULT_BLOCKED_DAYS = 10

OPEN_STATUSES = ("SENT", "RECEIVED", "MORE_INFO", "PROCESSING")
DEFAULT_STATUSES = list(OPEN_STATUSES)

__all__ = [
    "OPEN_STATUSES",
    "general_policy",
    "policy_for",
    "thresholds",
    "age_days",
    "is_overdue",
    "is_blocked",
    "overdue_q",
    "blocked_q",
]


def _scope(queryset, university):
    if university is None:
        return queryset
    return queryset.filter(Q(university=university) | Q(university__isnull=True))


def general_policy(university=None) -> SlaPolicy | None:
    """Règle générale active du périmètre (sans type de requête précis)."""
    return (
        _scope(SlaPolicy.objects.filter(is_active=True, problem_type__isnull=True), university)
        .order_by("name")
        .first()
    )


def policy_for(ticket, university=None) -> SlaPolicy | None:
    """Règle applicable à un ticket : catégorie d'abord, sinon générale."""
    specific = (
        SlaPolicy.objects.filter(
            is_active=True, problem_type_id=ticket.problem_type_id
        )
        .order_by("name")
        .first()
    )
    if specific is not None:
        return specific
    return general_policy(university)


def thresholds(ticket=None, university=None) -> tuple[int, int, SlaPolicy | None]:
    """(max_days, blocked_after_days, règle) pour un ticket ou un périmètre."""
    policy = policy_for(ticket, university) if ticket is not None else general_policy(university)
    if policy is None:
        return DEFAULT_MAX_DAYS, DEFAULT_BLOCKED_DAYS, None
    return policy.max_days, policy.blocked_after_days, policy


def age_days(ticket, now=None) -> float:
    """Âge du dossier (depuis la dernière mise à jour), en jours."""
    now = now or timezone.now()
    reference = ticket.updated_at or ticket.created_at
    if reference is None:
        return 0.0
    if timezone.is_naive(reference):
        reference = timezone.make_aware(reference)
    return (now - reference).total_seconds() / 86400


def _in_scope(ticket, policy) -> bool:
    statuses = policy.statuses_list if policy is not None else list(OPEN_STATUSES)
    return ticket.status in statuses


def is_overdue(ticket, university=None, now=None) -> bool:
    max_days, _, policy = thresholds(ticket, university)
    return _in_scope(ticket, policy) and age_days(ticket, now) > max_days


def is_blocked(ticket, university=None, now=None) -> bool:
    _, blocked_days, policy = thresholds(ticket, university)
    return _in_scope(ticket, policy) and age_days(ticket, now) > blocked_days


def overdue_q(university=None, now=None) -> Q:
    """Filtre SQL « en retard » (statuts suivis + dernière activité trop vieille)."""
    now = now or timezone.now()
    max_days, _, policy = thresholds(None, university)
    statuses = policy.statuses_list if policy is not None else list(OPEN_STATUSES)
    return Q(status__in=statuses) & Q(updated_at__lte=now - timedelta(days=max_days))


def blocked_q(university=None, now=None) -> Q:
    """Filtre SQL « bloqué » (au-delà du délai de blocage)."""
    now = now or timezone.now()
    _, blocked_days, policy = thresholds(None, university)
    statuses = policy.statuses_list if policy is not None else list(OPEN_STATUSES)
    return Q(status__in=statuses) & Q(updated_at__lte=now - timedelta(days=blocked_days))
