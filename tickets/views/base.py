"""
Vues HTML de tickets (fragments injectés dans #spa-viewport ou #modal-body).

`student_request_modal` : coquille du formulaire dynamique ; les champs
dépendants (UE, enseignants, pièces jointes) sont injectés par
`ticket_form_dynamic.js` après appel à l'endpoint form-config.
"""

from datetime import date

from django.shortcuts import render

from accounts.decorators import student_required
from core_scolarite.models import ProblemType

ACADEMIC_YEAR_SPAN = 4  # année courante + 3 précédentes


def academic_years(today: date | None = None) -> tuple[list[str], str]:
    """(années proposées, année courante) — session de rentrée en septembre."""
    today = today or date.today()
    start = today.year if today.month >= 9 else today.year - 1
    years = [f"{start - offset}-{start - offset + 1}" for offset in range(ACADEMIC_YEAR_SPAN)]
    return years, years[0]


@student_required
def student_request_modal(request):
    """Fragment de la modale « Nouvelle requête » (étudiant)."""
    years, current = academic_years()
    return render(
        request,
        "modals/student_request_form.html",
        {
            "problem_types": ProblemType.objects.only(
                "id", "name", "requires_course", "description"
            ).order_by("name"),
            "student": request.student,
            "academic_years": years,
            "current_academic_year": current,
        },
    )
