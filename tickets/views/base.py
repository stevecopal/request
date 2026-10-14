"""
Vues HTML de tickets (fragments injectés dans #spa-viewport ou #modal-body).

`student_request_modal` : coquille du formulaire dynamique ; les champs
dépendants (UE, enseignants, pièces jointes) sont injectés par
`ticket_form_dynamic.js` après appel à l'endpoint form-config.
"""

from django.shortcuts import render

from accounts.decorators import student_required
from core_scolarite.models import ProblemType


@student_required
def student_request_modal(request):
    """Fragment de la modale « Nouvelle requête » (étudiant)."""
    return render(
        request,
        "modals/student_request_form.html",
        {
            "problem_types": ProblemType.objects.only(
                "id", "name", "requires_course", "description"
            ).order_by("name"),
            "student": request.student,
        },
    )
