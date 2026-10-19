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
    Ticket.Status.PROCESSING: [
        Ticket.Status.RESOLVED,
        Ticket.Status.REJECTED,
        Ticket.Status.MORE_INFO,
    ],
    Ticket.Status.MORE_INFO: [
        Ticket.Status.PROCESSING,
        Ticket.Status.RESOLVED,
        Ticket.Status.REJECTED,
    ],
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
    more_info_request: str | None = None,
    notification_title: str | None = None,
    resolution_note: str | None = None,
) -> Ticket:
    """
    Applique une transition de statut validée et journalise l'entrée d'historique.

    Concurrence : la ligne est re-verrouillée (`select_for_update`) et
    re-validée dans la transaction — deux décisions simultanées (double-clic,
    deux onglets) ne peuvent pas produire un état incohérent : la seconde
    revoit un statut déjà muté et reçoit `StatusTransitionError`.

    :param actor: `User` ayant déclenché la transition (None = système).
    :param actor_role: rôle de l'acteur (student/teacher/system).
    :param note: note libre journalisée (ex. motif de rejet).
    :param more_info_request: question posée à l'étudiant (obligatoire sur MORE_INFO).
    :param notification_title: titre explicite de la notification (ex. réponse étudiant).
    :param resolution_note: réponse visible par l'étudiant (sur RESOLVED).
    :raises StatusTransitionError: transition invalide, instance périmée ou motif manquant.
    """
    # Re-verrouillage + relecture de la vérité terrain dans la transaction.
    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if locked.status != ticket.status:
        raise StatusTransitionError(
            _(
                "Cette requête vient d'être mise à jour par une autre action. "
                "Rechargez son état actuel (%(current)s) avant de recommencer."
            )
            % {"current": locked.get_status_display()}
        )

    allowed = ALLOWED_TRANSITIONS.get(locked.status, [])
    if new_status not in allowed:
        raise StatusTransitionError(
            _("Transition « %(from)s → %(to)s » non autorisée.")
            % {"from": locked.get_status_display(), "to": dict(Ticket.Status.choices).get(new_status, new_status)}
        )

    if new_status == Ticket.Status.REJECTED:
        reason = (reason or "").strip()
        if not reason:
            raise StatusTransitionError(
                _("Un motif est obligatoire pour rejeter une requête."),
                {"rejection_reason": _("Champ obligatoire.")},
            )
        locked.rejection_reason = reason
    else:
        locked.rejection_reason = None

    if new_status == Ticket.Status.MORE_INFO:
        more_info_request = (more_info_request or reason or "").strip()
        if not more_info_request:
            raise StatusTransitionError(
                _("Une question est obligatoire pour demander des informations."),
                {"complementary_info_request": _("Champ obligatoire.")},
            )
        locked.complementary_info_request = more_info_request
    elif new_status == Ticket.Status.PROCESSING:
        # La question reste consultable dans l'historique ; on l'archive à la reprise.
        locked.complementary_info_request = ""

    # Réponse visible par l'étudiant sur une validation (jamais sur un rejet,
    # qui porte déjà son motif obligatoire).
    if new_status == Ticket.Status.RESOLVED:
        locked.resolution_note = (resolution_note or "").strip()
    else:
        locked.resolution_note = ""

    previous_status = locked.status
    now = timezone.now()
    locked.status = new_status
    # Mémorise l'acteur pour le signal post_save (notifications) : le
    # destinataire de l'événement ne reçoit jamais sa propre action.
    locked._actor_user_id = getattr(actor, "id", None)
    if notification_title:
        locked._notification_title = str(notification_title)
    if new_status == Ticket.Status.RECEIVED and locked.received_at is None:
        locked.received_at = now
    if new_status in (Ticket.Status.RESOLVED, Ticket.Status.REJECTED):
        locked.resolved_at = now

    locked.save(
        update_fields=[
            "status",
            "rejection_reason",
            "resolution_note",
            "complementary_info_request",
            "received_at",
            "resolved_at",
            "updated_at",
        ]
    )

    TicketStatusHistory.objects.create(
        ticket=locked,
        from_status=previous_status,
        to_status=new_status,
        actor=actor,
        actor_role=actor_role,
        note=(note or "").strip()
        or (more_info_request if new_status == Ticket.Status.MORE_INFO else "")
        or (locked.resolution_note if new_status == Ticket.Status.RESOLVED else "")
        or str(_("Statut mis à jour.")),
    )

    # Recopie de l'état verrouillé sur l'instance appelante (ergonomie appelant).
    for field in (
        "status",
        "rejection_reason",
        "resolution_note",
        "complementary_info_request",
        "received_at",
        "resolved_at",
        "updated_at",
    ):
        setattr(ticket, field, getattr(locked, field))
    ticket._actor_user_id = getattr(actor, "id", None)
    if notification_title:
        ticket._notification_title = str(notification_title)
    return ticket
