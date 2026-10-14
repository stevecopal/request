"""
Signaux temps réel de l'app tickets (ARCHITECTURE §10.3, Prompt 17).

`post_save(Ticket)` diffuse un payload vers `user_{student.user_id}` ET
`user_{teacher.user_id}` : chaque partie voit le changement de statut
instantanément, sans rechargement de page.

Le même commit crée les lignes `accounts.Notification` du centre de
notifications (jamais pour l'acteur de l'événement) et le payload WS embarque
le compteur de notifications non lus de chaque destinataire.

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
    message = dict(payload)
    # Compteur de notifications non lus du destinataire (badge de navigation).
    from accounts.models import Notification

    message["unread_notifications"] = Notification.objects.filter(
        user_id=user_id, is_read=False
    ).count()
    async_to_sync(channel_layer.group_send)(
        f"user_{user_id}",
        {"type": "ticket.status.changed", "message": message},
    )


def _push_notification(user_id, title, body, tag):
    """Web Push best-effort (distinct des WebSockets : notifie appareil fermé)."""
    try:
        from accounts.services.webpush import send_to_user
    except ImportError:
        return
    send_to_user(user_id, title=title, body=body, tag=tag, url="/dashboard/")


def _notification_text(instance, created):
    """(titre, corps) adaptés au destinataire et à l'événement."""
    problem_type = instance.problem_type
    if created:
        return (
            str(_("Nouvelle requête")),
            f"{problem_type} — {instance.student.full_name}",
        )
    if instance.status == Ticket.Status.MORE_INFO:
        title = str(_("Informations complémentaires demandées"))
    elif instance.status == Ticket.Status.REJECTED:
        title = str(_("Requête rejetée"))
    elif instance.status == Ticket.Status.RESOLVED:
        title = str(_("Requête résolue"))
    else:
        title = str(_("Statut mis à jour"))
    return title, f"{problem_type} — {instance.status_label}"


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
    # Acteur de l'événement (posé par apply_status / ticket_creator avant save) :
    # ne jamais créer de notification pour une action que l'on vient de faire.
    actor_user_id = getattr(instance, "_actor_user_id", None)

    def _emit():
        from accounts.models import Notification

        recipients = {student_user_id, teacher_user_id} - {actor_user_id}
        if recipients:
            title, body = _notification_text(instance, created)
            Notification.objects.bulk_create(
                [
                    Notification(
                        user_id=user_id,
                        ticket=instance,
                        title=str(title),
                        body=str(body),
                    )
                    for user_id in recipients
                ]
            )

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
