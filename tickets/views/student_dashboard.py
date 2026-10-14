"""
Flux étudiant — tickets (ARCHITECTURE §7.3, Prompt 13).

Liste les requêtes de l'étudiant connecté (binding session uniquement),
optimisée avec `select_related` (anti N+1). Le rendu des cartes, des badges
de statut et du panneau de motif de rejet est délégué au template.
"""

from django.shortcuts import render

from accounts.decorators import student_required
from tickets.models import Ticket


@student_required
def student_feed(request):
    """Fragment « Mes requêtes » (étudiant)."""
    tickets = (
        Ticket.objects.filter(student=request.student)
        .select_related("course", "problem_type", "teacher__user")
        .order_by("-created_at")
    )
    return render(request, "partials/student_feed.html", {"tickets": tickets})
