"""
Analytique super-admin — core_scolarite (ARCHITECTURE §12, Prompt 20).

Calcule en une passe (agrégations ORM) :
  * total des requêtes, non résolues, résolues, refusées ;
  * temps de réponse moyen par faculté (created_at → resolved_at) ;
  * répartition par statut + top catégories/départements ;
  * indicateurs SLA (retard / blocage) partagés avec C3 et C5 ;
  * dernières transitions (fil d'activité) et accès rapides aux modules C1–C6.

Le tout est rendu dans `partials/admin_metrics.html` (mobile-first).
"""

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from accounts.decorators import superuser_required
from accounts.utils import ROLE_ADMIN, nav_sections
from core_scolarite.services import metrics as metrics_service
from core_scolarite.services.reports import build_stats, tickets_queryset
from core_scolarite.services.scoping import resolve_university
from tickets.models import Ticket, TicketStatusHistory

OPEN_STATUSES = [
    Ticket.Status.SENT,
    Ticket.Status.RECEIVED,
    Ticket.Status.MORE_INFO,
    Ticket.Status.PROCESSING,
]


@superuser_required
def admin_analytics(request):
    """Fragment du tableau de bord analytique (super-admin uniquement)."""
    university = resolve_university(request)
    scope_qs = tickets_queryset({}, university, select_related=False)
    stats = build_stats(scope_qs, university=university)

    global_totals = scope_qs.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
        rejected=Count("id", filter=Q(status=Ticket.Status.REJECTED)),
    )

    response_time = ExpressionWrapper(
        F("resolved_at") - F("created_at"), output_field=DurationField()
    )

    per_faculty = list(
        scope_qs.values("student__faculty__name")
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

    max_days, blocked_days, _ = metrics_service.thresholds(None, university)

    recent = (
        TicketStatusHistory.objects.select_related("ticket__student__user", "actor")
        .order_by("-created_at")[:6]
    )

    context = {
        "totals": global_totals,
        "per_faculty": per_faculty,
        "stats": stats,
        "max_days": max_days,
        "blocked_days": blocked_days,
        "recent": recent,
        # Accès rapides : items « fragment » de la navigation admin (sans modales).
        "quick_links": [
            item
            for section in nav_sections(ROLE_ADMIN)
            for item in section["items"]
            if not item["is_modal"]
        ],
    }
    return render(request, "partials/admin_metrics.html", context)
