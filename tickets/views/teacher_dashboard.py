"""
Boîte enseignant — tickets (ARCHITECTURE §7.3, Prompt 14).

  * `teacher_inbox` : requêtes assignées, priorité aux non traitées, puis
    chronologie. Les tickets SENT sont acquittés automatiquement (→ RECEIVED)
    dès qu'ils apparaissent dans la boîte (déclenche le signal temps réel).
  * `ticket_detail` : détail sans rechargement ; accès réservé au propriétaire
    étudiant OU à l'enseignant assigné (sinon 403).
  * `download_attachment` : service de fichier protégé (jamais d'URL publique).
"""

from django.db.models import Case, IntegerField, Value, When
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _

from accounts.decorators import login_required_json, teacher_required
from tickets.models import Ticket, TicketAttachment, TicketStatusHistory
from tickets.services.status_machine import apply_status

# Priorité d'affichage : non traitées d'abord.
STATUS_PRIORITY = Case(
    When(status=Ticket.Status.SENT, then=Value(0)),
    When(status=Ticket.Status.RECEIVED, then=Value(1)),
    When(status=Ticket.Status.MORE_INFO, then=Value(2)),
    When(status=Ticket.Status.PROCESSING, then=Value(3)),
    When(status=Ticket.Status.REJECTED, then=Value(4)),
    When(status=Ticket.Status.RESOLVED, then=Value(5)),
    output_field=IntegerField(),
)


@teacher_required
def teacher_inbox(request):
    """Fragment « À traiter » (enseignant)."""
    queryset = Ticket.objects.filter(teacher=request.teacher).select_related(
        "student__user", "course", "problem_type"
    )

    # Acquittement automatique : SENT → RECEIVED à l'ouverture de l'inbox.
    for ticket in list(queryset.filter(status=Ticket.Status.SENT)):
        apply_status(
            ticket,
            Ticket.Status.RECEIVED,
            actor=ticket.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            note=str(_("Acquittement automatique à l'ouverture de la boîte.")),
        )

    tickets = queryset.order_by(STATUS_PRIORITY, "-created_at")
    return render(request, "partials/teacher_inbox.html", {"tickets": tickets})


def _get_accessible_ticket(request, pk):
    """Renvoie le ticket si l'utilisateur y a droit, sinon (None, réponse d'erreur)."""
    ticket = (
        Ticket.objects.select_related(
            "student__user", "teacher__user", "course", "problem_type"
        )
        .prefetch_related("status_history__actor", "attachments__config")
        .filter(pk=pk)
        .first()
    )
    if ticket is None:
        return None, JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )

    student_profile = getattr(request.user, "student_profile", None)
    teacher_profile = getattr(request.user, "teacher_profile", None)
    if student_profile and ticket.student_id == student_profile.id:
        return ticket, None
    if teacher_profile and ticket.teacher_id == teacher_profile.id:
        return ticket, None
    return None, JsonResponse(
        {"status": "error", "message": str(_("Accès non autorisé."))}, status=403
    )


@teacher_required
def teacher_decision_modal(request):
    """Fragment de la modale de décision (Valider / Rejeter / Plus d'infos)."""
    ticket_id = request.GET.get("ticket_id")
    target = request.GET.get("target")
    allowed_targets = (
        Ticket.Status.RESOLVED,
        Ticket.Status.REJECTED,
        Ticket.Status.MORE_INFO,
    )
    if target not in allowed_targets:
        return JsonResponse(
            {"status": "error", "message": str(_("Cible de décision invalide."))},
            status=400,
        )
    ticket = Ticket.objects.filter(pk=ticket_id, teacher=request.teacher).first()
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )
    return render(
        request,
        "modals/teacher_decision.html",
        {"ticket": ticket, "target": target},
    )


@login_required_json
def ticket_detail(request, pk):
    """Fragment de détail d'un ticket (propriétaire ou enseignant assigné)."""
    ticket, error = _get_accessible_ticket(request, pk)
    if error:
        return error
    return render(request, "partials/teacher_ticket_detail.html", {"ticket": ticket})


@login_required_json
def download_attachment(request, pk):
    """Téléchargement protégé d'une pièce jointe (contrôle d'appartenance)."""
    attachment = get_object_or_404(
        TicketAttachment.objects.select_related("ticket__student", "ticket__teacher"),
        pk=pk,
    )
    ticket, error = _get_accessible_ticket(request, attachment.ticket_id)
    if error:
        return error

    response = FileResponse(attachment.file.open("rb"))
    response["Content-Type"] = "application/octet-stream"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = (
        f'attachment; filename="{attachment.file.name.rsplit("/", 1)[-1]}"'
    )
    return response
