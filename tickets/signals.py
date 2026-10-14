"""
Signaux temps réel de l'app tickets (ARCHITECTURE §10.3, Prompt 17).

`post_save(Ticket)` diffuse un payload vers `user_{student.user_id}` ET
`user_{teacher.user_id}` : chaque partie voit le changement de statut
instantanément, sans rechargement de page.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver

from tickets.models import Ticket


def _broadcast(user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {"type": "ticket.status.changed", "message": payload},
    )


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

    for user_id in {instance.student.user_id, instance.teacher.user_id}:
        _broadcast(user_id, payload)
