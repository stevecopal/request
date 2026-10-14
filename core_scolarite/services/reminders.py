"""
Relances configurables — calcul des requêtes éligibles et envoi.

`ReminderPolicy` décrit une relance (délai, destinataire, message) ; ce module
calcule les tickets éligibles (aucune relance récente pour le même titre) puis
crée les notifications dans une transaction. Utilisable par la commande
`send_reminders` ou directement depuis la console (aperçu avant envoi).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import Notification, University
from core_scolarite.models import ReminderPolicy
from tickets.models import Ticket

OPEN_STATUSES = [
    Ticket.Status.SENT,
    Ticket.Status.RECEIVED,
    Ticket.Status.MORE_INFO,
    Ticket.Status.PROCESSING,
]

__all__ = ["collect_due", "send_due"]


def _scope(queryset, university: University | None):
    if university is None:
        return queryset
    return queryset.filter(student__faculty__university=university)


def collect_due(
    policy: ReminderPolicy, university: University | None = None, now=None
) -> list[tuple[Ticket, object]]:
    """
    Requêtes ouvertes éligibles à une relance : aucun changement de statut
    depuis `delay_days` et pas déjà relancée dans cette fenêtre.
    """
    now = now or timezone.now()
    threshold = now - timedelta(days=policy.delay_days)

    queryset = _scope(
        Ticket.objects.filter(status__in=OPEN_STATUSES, updated_at__lte=threshold),
        university or policy.university,
    ).select_related("student__user", "teacher__user")

    due = []
    for ticket in queryset:
        recipient = (
            ticket.student.user
            if policy.target_role == ReminderPolicy.TargetRole.STUDENT
            else ticket.teacher.user
        )
        already = Notification.objects.filter(
            user=recipient, ticket=ticket, title=policy.title, created_at__gte=threshold
        ).exists()
        if not already and recipient is not None:
            due.append((ticket, recipient))
    return due


def send_due(pairs: list[tuple[Ticket, object]], policy: ReminderPolicy) -> int:
    """Crée les notifications de relance (transaction atomique). Compteur renvoyé."""
    if not pairs:
        return 0
    default_body = str(
        _("Une requête académique attend un traitement depuis %(days)s jour(s).")
        % {"days": policy.delay_days}
    )
    created = 0
    with transaction.atomic():
        for ticket, recipient in pairs:
            Notification.objects.create(
                user=recipient,
                ticket=ticket,
                title=policy.title,
                body=policy.message or default_body,
            )
            created += 1
    return created
