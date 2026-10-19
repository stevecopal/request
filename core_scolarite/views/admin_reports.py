"""
C5 — Statistiques & rapports (console super-admin).

  GET  admin/reports/          filtres + indicateurs + liens d'export (fragment)
  GET  admin/reports/csv/?kind= export CSV (UTF-8 BOM, `;` — Excel FR)
  GET  admin/reports/pdf/?kind= export PDF (reportlab, paysage A4)

Les indicateurs et jeux de lignes proviennent de `services/reports.py`
(même moteur pour l'écran et les exports — aucun écart possible entre le
tableau affiché et le fichier téléchargé). Chaque export est journalisé
au journal d'audit (`EXPORT`).
"""

from __future__ import annotations

from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from accounts.decorators import console_required
from core_scolarite.services import reports as reports_service
from core_scolarite.services.scoping import resolve_university

from .common import json_error

PERMS = ("tickets.view_ticket", "core_scolarite.view_auditlog")

KIND_LABELS = {
    "synthese": _("Synthèse (indicateurs)"),
    "requetes": _("Requêtes (détail)"),
    "utilisateurs": _("Utilisateurs"),
    "journal": _("Journal d'audit"),
    "historique": _("Historique des statuts"),
}


@console_required(*PERMS)
def admin_reports(request):
    """Fragment C5 : filtres, KPI, répartitions et exports."""
    university = resolve_university(request)
    filters = reports_service.parse_filters(request, university)
    form = filters["form"]
    qs = reports_service.tickets_queryset(
        filters, university, select_related=False
    )
    stats = reports_service.build_stats(qs, university=university)

    active_qs = "&".join(f"{k}={v}" for k, v in form.active_filters().items())
    exports = []
    for kind, label in KIND_LABELS.items():
        query = f"kind={kind}" + (f"&{active_qs}" if active_qs else "")
        exports.append(
            {
                "kind": kind,
                "label": label,
                "csv_url": f"{reverse('core_scolarite:admin_reports_csv')}?{query}",
                "pdf_url": f"{reverse('core_scolarite:admin_reports_pdf')}?{query}",
            }
        )

    context = {
        "filter_form": form,
        "stats": stats,
        "exports": exports,
        "has_filters": bool(form.active_filters()),
        "active_qs": active_qs,
        "total_all": reports_service.tickets_queryset(
            {}, university, select_related=False
        ).count(),
    }
    return render(request, "partials/admin/reports.html", context)


@require_GET
@console_required(*PERMS)
def admin_reports_csv(request):
    kind = request.GET.get("kind") or ""
    if kind not in reports_service.KINDS:
        return json_error(_("Jeu d'export inconnu."), status=400)
    university = resolve_university(request)
    return reports_service.csv_response(request, kind, university)


@require_GET
@console_required(*PERMS)
def admin_reports_pdf(request):
    kind = request.GET.get("kind") or ""
    if kind not in reports_service.KINDS:
        return json_error(_("Jeu d'export inconnu."), status=400)
    university = resolve_university(request)
    return reports_service.pdf_response(request, kind, university)
