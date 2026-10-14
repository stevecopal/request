"""
Analytique super-admin — core_scolarite (ARCHITECTURE §12, Prompt 20).

Calcule en une passe (agrégations ORM) :
  * total des requêtes ;
  * requêtes non résolues (SENT / RECEIVED / PROCESSING) ;
  * temps de réponse moyen par faculté (created_at → resolved_at) ;
  * répartition par statut.

Le tout est rendu dans `partials/admin_metrics.html` (mobile-first).
"""

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from accounts.decorators import superuser_required
from tickets.models import Ticket

OPEN_STATUSES = [
    Ticket.Status.SENT,
    Ticket.Status.RECEIVED,
    Ticket.Status.PROCESSING,
]


@superuser_required
def admin_analytics(request):
    """Fragment du tableau de bord analytique (super-admin uniquement)."""
    global_totals = Ticket.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
        rejected=Count("id", filter=Q(status=Ticket.Status.REJECTED)),
    )

    response_time = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )

    per_faculty = list(
        Ticket.objects.values("student__faculty__name")
        .annotate(
            total=Count("id"),
            pending=Count("id", filter=Q(status__in=OPEN_STATUSES)),
            resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
            avg_response=Avg(
                response_time,
                filter=Q(status=Ticket.Status.RESOLVED, resolved_at__isnull=False),
            ),
        )
        .order_by("-total")
    )

    # Conversion du DurationField en heures lisibles pour le template.
    for row in per_faculty:
        avg = row["avg_response"]
        row["avg_response_hours"] = round(avg.total_seconds() / 3600, 1) if avg else None
        row["faculty_name"] = row["student__faculty__name"] or str(_("Non rattaché"))

    context = {
        "totals": global_totals,
        "per_faculty": per_faculty,
    }
    return render(request, "partials/admin_metrics.html", context)
