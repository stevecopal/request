"""
Actions AJAX de tickets (création) — ARCHITECTURE §7.3, Prompt 12.

Règle anti-falsification (IDOR) : l'étudiant est **toujours** lié à
`request.user.student_profile`. Aucun identifiant de profil n'est lu dans la
requête : impossible de créer une requête pour un autre étudiant.
"""

from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import student_required
from tickets.services.ticket_creator import TicketCreationError, create_student_ticket

ATTACHMENT_PREFIX = "attachment_"


@require_POST
@student_required
def create_ticket(request):
    """Soumission d'une requête étudiante (multipart) → 201 | 400."""
    uploaded_files = {}
    for field_name, uploaded in request.FILES.items():
        if field_name.startswith(ATTACHMENT_PREFIX):
            config_id = field_name[len(ATTACHMENT_PREFIX):]
            uploaded_files[config_id] = uploaded

    try:
        ticket = create_student_ticket(
            student_profile=request.student,
            problem_type_id=request.POST.get("problem_type_id"),
            description=request.POST.get("description", ""),
            uploaded_files_dict=uploaded_files,
            course_id=request.POST.get("course_id") or None,
            teacher_id=request.POST.get("teacher_id") or None,
            academic_year=request.POST.get("academic_year", ""),
        )
    except TicketCreationError as exc:
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
            "message": str(_("Requête soumise avec succès.")),
            "ticket_id": str(ticket.id),
            "status_label": ticket.status_label,
        },
        status=201,
    )
