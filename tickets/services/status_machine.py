"""
Machine à états des tickets — tickets (ARCHITECTURE §6.4, Prompt 15).

Transitions autorisées :
  SENT → RECEIVED → PROCESSING → {RESOLVED, REJECTED}
Toute transition hors table est refusée. `apply_status()` pose les horodatages
d'analytique (`received_at`, `resolved_at`) et une entrée d'historique
immuable (`TicketStatusHistory`) de façon atomique.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from tickets.models import Ticket, TicketStatusHistory

ALLOWED_TRANSITIONS = {
    Ticket.Status.SENT: [Ticket.Status.RECEIVED],
    Ticket.Status.RECEIVED: [Ticket.Status.PROCESSING],
    Ticket.Status.PROCESSING: [Ticket.Status.RESOLVED, Ticket.Status.REJECTED],
    Ticket.Status.RESOLVED: [],
    Ticket.Status.REJECTED: [],
}


class StatusTransitionError(Exception):
    """Transition de statut interdite ou motif de rejet manquant."""

    def __init__(self, message, field_errors=None):
        self.message = str(message)
        self.field_errors = field_errors or {}
        super().__init__(self.message)


@transaction.atomic
def apply_status(
    ticket: Ticket,
    new_status: str,
    reason: str | None = None,
    actor=None,
    actor_role: str = TicketStatusHistory.ActorRole.SYSTEM,
    note: str = "",
) -> Ticket:
    """
    Applique une transition de statut validée et journalise l'entrée d'historique.

    :param actor: `User` ayant déclenché la transition (None = système).
    :param actor_role: rôle de l'acteur (student/teacher/system).
    :param note: note libre journalisée (ex. motif de rejet).
    :raises StatusTransitionError: transition invalide ou motif manquant.
    """
    allowed = ALLOWED_TRANSITIONS.get(ticket.status, [])
    if new_status not in allowed:
        raise StatusTransitionError(
            _("Transition « %(from)s → %(to)s » non autorisée.")
            % {"from": ticket.get_status_display(), "to": dict(Ticket.Status.choices).get(new_status, new_status)}
        )

    if new_status == Ticket.Status.REJECTED:
        reason = (reason or "").strip()
        if not reason:
            raise StatusTransitionError(
                _("Un motif est obligatoire pour rejeter une requête."),
                {"rejection_reason": _("Champ obligatoire.")},
            )
        ticket.rejection_reason = reason
    else:
        ticket.rejection_reason = None

    previous_status = ticket.status
    now = timezone.now()
    ticket.status = new_status
    if new_status == Ticket.Status.RECEIVED and ticket.received_at is None:
        ticket.received_at = now
    if new_status in (Ticket.Status.RESOLVED, Ticket.Status.REJECTED):
        ticket.resolved_at = now

    ticket.save(
        update_fields=[
            "status",
            "rejection_reason",
            "received_at",
            "resolved_at",
            "updated_at",
        ]
    )

    TicketStatusHistory.objects.create(
        ticket=ticket,
        from_status=previous_status,
        to_status=new_status,
        actor=actor,
        actor_role=actor_role,
        note=(note or "").strip() or str(_("Statut mis à jour.")),
    )
    return ticket
