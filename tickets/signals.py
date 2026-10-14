"""
Signaux temps réel de l'app tickets (ARCHITECTURE §10.3, Prompt 17).

`post_save(Ticket)` diffuse un payload vers `user_{student.user_id}` ET
`user_{teacher.user_id}` : chaque partie voit le changement de statut
instantanément, sans rechargement de page.

Sécurité transactionnelle : la diffusion n'est enregistrée qu'après le
commit effectif (`transaction.on_commit`) — aucun événement n'est émis pour
une transaction annulée, et le client ne reçoit jamais un statut qui n'existe
pas encore en base.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from tickets.models import Ticket


def _broadcast(user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {"type": "ticket.status.changed", "message": payload},
    )


def _push_notification(user_id, title, body, tag):
    """Web Push best-effort (distinct des WebSockets : notifie appareil fermé)."""
    try:
        from accounts.services.webpush import send_to_user
    except ImportError:
        return
    send_to_user(user_id, title=title, body=body, tag=tag, url="/dashboard/")


@receiver(post_save, sender=Ticket)
def ticket_post_save(sender, instance, created, **kwargs):
    """Diffuse l'état d'un ticket aux canaux de l'étudiant et de l'enseignant."""
    payload = {
        "type": "ticket.status.changed",
        "ticket_id": str(instance.id),
        "status": instance.status,
        "status_label": instance.status_label,
        "rejection_reason": instance.rejection_reason,
        "created": created,
    }

    student_user_id = instance.student.user_id
    teacher_user_id = instance.teacher.user_id

    def _emit():
        for user_id in {student_user_id, teacher_user_id}:
            _broadcast(user_id, payload)
        # Notification push hors-page (best-effort, jamais bloquante).
        verb = _("Nouvelle requête") if created else _("Statut mis à jour")
        title = str(verb)
        body = f"{instance.problem_type} — {payload['status_label']}"
        tag = f"ticket-{instance.id}"
        for user_id in {student_user_id, teacher_user_id}:
            _push_notification(user_id, title, body, tag)

    transaction.on_commit(_emit)
