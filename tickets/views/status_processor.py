"""
Traitement des statuts — tickets (ARCHITECTURE §7.3, Prompt 15).

Sécurité : un enseignant ne peut faire muter QUE les tickets qui lui sont
assignés → sinon 403 Forbidden. Un rejet sans motif est refusé (400).
"""

from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from tickets.models import Ticket
from tickets.services.status_machine import StatusTransitionError, apply_status


@require_POST
@teacher_required
def update_status(request):
    """Change le statut d'un ticket assigné à l'enseignant connecté."""
    ticket_id = request.POST.get("ticket_id")
    new_status = request.POST.get("status")
    reason = request.POST.get("rejection_reason")

    if not ticket_id or not new_status:
        return JsonResponse(
            {"status": "error", "message": str(_("Paramètres manquants."))}, status=400
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
        apply_status(ticket, new_status, reason=reason)
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
