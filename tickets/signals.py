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

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from tickets.models import Ticket

logger = logging.getLogger(__name__)


def _broadcast(user_id, payload):
    """
    Diffusion WebSocket **best-effort** : une panne du channel layer (Redis en
    timeout, redémarrage…) ne doit jamais faire échouer la requête HTTP qui vient
    d'enregistrer le ticket. L'événement perdu est journalisé, la base reste
    la source de vérité (l'écran se resynchronise au rechargement).
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    message = dict(payload)
    # Compteur de notifications non lus du destinataire (badge de navigation).
    from accounts.models import Notification

    message["unread_notifications"] = Notification.objects.filter(
        user_id=user_id, is_read=False
    ).count()
    try:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {"type": "ticket.status.changed", "message": message},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort assumé : Redis en
        # timeout/redémarrage ne doit jamais faire échouer la requête qui vient
        # d'enregistrer le ticket. La base reste la source de vérité.
        logger.warning(
            "Diffusion temps réel impossible (channel layer indisponible) : %r", exc
        )


def _push_notification(user_id, title, body, tag):
    """Web Push best-effort (distinct des WebSockets : notifie appareil fermé)."""
    try:
        from accounts.services.webpush import send_to_user
    except ImportError:
        return
    try:
        send_to_user(user_id, title=title, body=body, tag=tag, url="/dashboard/")
    except Exception:  # noqa: BLE001 — jamais bloquant (best-effort)
        logger.warning("Envoi push impossible pour l'utilisateur %s", user_id, exc_info=True)


def _notification_text(instance, created):
    """(titre, corps) adaptés au destinataire et à l'événement."""
    problem_type = instance.problem_type
    # Titre explicite posé par la vue (ex. « Réponse de l'étudiant »,
    # « Nouvelle affectation ») — prioritaire sur le libellé générique.
    override = getattr(instance, "_notification_title", None)
    if override:
        return str(override), f"{problem_type} — {instance.status_label}"
    if created:
        return (
            str(_("Nouvelle requête")),
            f"{problem_type} — {instance.student.full_name}",
        )
    if instance.status == Ticket.Status.RECEIVED:
        title = str(_("Requête reçue"))
    elif instance.status == Ticket.Status.PROCESSING:
        title = str(_("Prise en charge — en cours de traitement"))
    elif instance.status == Ticket.Status.MORE_INFO:
        title = str(_("Informations complémentaires demandées"))
    elif instance.status == Ticket.Status.REJECTED:
        title = str(_("Requête rejetée"))
    elif instance.status == Ticket.Status.RESOLVED:
        title = str(_("Requête résolue"))
        # La réponse rédigée par l'enseignant est embarquée dans la
        # notification : l'étudiant lit la solution sans ouvrir le dossier.
        answer = (instance.resolution_note or "").strip()
        if answer:
            if len(answer) > 160:
                answer = answer[:157] + "…"
            return title, f"{problem_type} — {answer}"
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

        # Les membres actifs du service destinataire voient aussi le dossier
        # (transmission B6) : ils reçoivent les mêmes événements.
        service_user_ids = set()
        if instance.assigned_service_id:
            from core_scolarite.models import ServiceAssignment

            service_user_ids = set(
                ServiceAssignment.objects.filter(
                    service_id=instance.assigned_service_id, is_active=True
                ).values_list("user_id", flat=True)
            )

        audience = {student_user_id, teacher_user_id} | service_user_ids
        recipients = audience - {actor_user_id}
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

        for user_id in audience:
            _broadcast(user_id, payload)
        # Notification push hors-page (best-effort, jamais bloquante).
        title, body = _notification_text(instance, created)
        tag = f"ticket-{instance.id}"
        for user_id in recipients:
            _push_notification(user_id, title, body, tag)

    transaction.on_commit(_emit)
