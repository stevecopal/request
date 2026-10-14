"""
Traitement des statuts — tickets (ARCHITECTURE §7.3, Prompt 15).

Sécurité : un enseignant ne peut faire muter QUE les tickets qui lui sont
assignés → sinon 403 Forbidden. Un rejet sans motif est refusé (400).
La demande d'informations complémentaires (MORE_INFO) est soumise au feature
flag `ENABLE_TEACHER_MORE_INFO` (désactivé → 400, jamais d'effet de bord).
La transition réelle passe par `apply_status` qui re-verrouille la ligne
(`select_for_update`) : deux décisions concurrentes ne peuvent pas se
marcher dessus.
"""

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from tickets.models import Ticket, TicketStatusHistory
from tickets.services.status_machine import StatusTransitionError, apply_status


@require_POST
@teacher_required
def update_status(request):
    """Change le statut d'un ticket assigné à l'enseignant connecté."""
    ticket_id = request.POST.get("ticket_id")
    new_status = request.POST.get("status")
    reason = request.POST.get("rejection_reason")
    more_info_request = request.POST.get("more_info_request")

    if not ticket_id or not new_status:
        return JsonResponse(
            {"status": "error", "message": str(_("Paramètres manquants."))}, status=400
        )

    if new_status == Ticket.Status.MORE_INFO and not settings.ENABLE_TEACHER_MORE_INFO:
        return JsonResponse(
            {
                "status": "error",
                "message": str(
                    _("La demande d'informations complémentaires est désactivée.")
                ),
            },
            status=400,
        )

    ticket = Ticket.objects.filter(pk=ticket_id).first()
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )

    # Contrôle d'appartenance : jamais de mutation sur le ticket d'un autre.
    if ticket.teacher_id != request.teacher.id:
        return JsonResponse(
            {"status": "error", "message": str(_("Action non autorisée."))}, status=403
        )

    try:
        apply_status(
            ticket,
            new_status,
            reason=reason,
            actor=request.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            note=(reason or "").strip(),
            more_info_request=more_info_request,
        )
    except StatusTransitionError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": exc.message,
                "errors": exc.field_errors,
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Statut mis à jour.")),
            "ticket": {
                "id": str(ticket.id),
                "status": ticket.status,
                "status_label": ticket.status_label,
            },
        }
    )
