"""
C3 — Suivi central des requêtes (console super-admin) : **consultation seule**.

  GET  admin/requests/                 filtres + liste + panneau de détail
  GET  admin/requests/list/            liste seule (rafraîchissement)
  GET  admin/requests/detail/?ticket=… fiche détaillée (statut + temps de traitement)

Droits : `tickets.view_ticket`. L'admin ne pilote **ni le statut ni
l'affectation** : acquittement, prise en charge, demande d'informations et
décision sont des actes de l'enseignant (espace enseignant), et la
réaffectation passe par la transmission enseignant → enseignant/service.
"""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.decorators import console_required
from accounts.models import Faculty
from accounts.spa import spa_page
from core_scolarite.forms import AdminRequestFilterForm
from core_scolarite.services import metrics as metrics_service
from core_scolarite.services.scoping import resolve_university
from tickets.models import Ticket

from .common import json_error, paginate

READ_PERMS = ("tickets.view_ticket",)

PAGE_SIZE = 25


def _scope_tickets(qs, university):
    if university is None:
        return qs
    return qs.filter(
        Q(student__faculty__university=university)
        | Q(student__faculty__isnull=True)
        | Q(student__isnull=True)
    )


def filtered_tickets(request, form, university):
    qs = Ticket.objects.select_related(
        "student__user",
        "student__faculty",
        "student__department",
        "teacher__user",
        "course",
        "problem_type",
    )
    qs = _scope_tickets(qs, university)
    if not form.is_bound:
        return qs.order_by("-created_at")

    data = form.cleaned_data if form.is_valid() else {}
    query = (data.get("q") or "").strip()
    if query:
        qs = qs.filter(
            Q(student__user__username__icontains=query)
            | Q(student__user__first_name__icontains=query)
            | Q(student__user__last_name__icontains=query)
            | Q(student__registration_number__icontains=query)
            | Q(description__icontains=query)
            | Q(problem_type__name__icontains=query)
            | Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
        )
    if data.get("status"):
        qs = qs.filter(status=data["status"])
    if data.get("faculty"):
        qs = qs.filter(student__faculty=data["faculty"])
    if data.get("department"):
        qs = qs.filter(student__department=data["department"])
    if data.get("problem_type"):
        qs = qs.filter(problem_type=data["problem_type"])
    if data.get("date_from"):
        qs = qs.filter(created_at__gte=data["date_from"])
    if data.get("date_to"):
        qs = qs.filter(created_at__lte=data["date_to"])
    if data.get("overdue"):
        qs = qs.filter(metrics_service.overdue_q(university=university))
    if data.get("escalated"):
        qs = qs.filter(is_escalated=True)
    return qs.order_by("-created_at")


def _filter_context(request, university, bound_form=None):
    form = bound_form or AdminRequestFilterForm(
        request.GET if request.GET else None, university=university
    )
    faculties = Faculty.objects.filter(is_active=True)
    if university is not None:
        faculties = faculties.filter(university=university)
    return form, {
        "filter_form": form,
        "faculties": faculties.order_by("name"),
        "active_qs": "&".join(
            f"{k}={v}" for k, v in form.active_filters().items()
        ),
        "active": form.active_filters(),
        "has_filters": bool(form.active_filters()),
    }


def _format_duration(delta):
    """Durée humaine compacte : « 2 j 4 h », « 5 h 12 min », « 40 min »."""
    total = max(int(delta.total_seconds()), 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return _("%(days)d j %(hours)d h") % {"days": days, "hours": hours}
    if hours:
        return _("%(hours)d h %(minutes)02d min") % {
            "hours": hours,
            "minutes": minutes,
        }
    return _("%(minutes)d min") % {"minutes": minutes}


def processing_time(ticket):
    """Temps de traitement d'une requête.

    Terminée (RESOLVED/REJECTED, `resolved_at` posé) : durée réelle
    `resolved_at - created_at`. En cours : temps écoulé depuis la soumission.
    """
    closed_at = ticket.resolved_at
    end = closed_at or timezone.now()
    return {
        "duration": _format_duration(end - ticket.created_at),
        "is_done": closed_at is not None,
        "closed_at": closed_at,
    }


def _annotate_processing(rows):
    """Pose `ticket.processing` sur chaque ligne de la liste (25 max)."""
    for ticket in rows:
        ticket.processing = processing_time(ticket)
    return rows


@spa_page
@console_required(*READ_PERMS)
def admin_requests(request):
    """Fragment C3 : filtres, liste paginée (statut + temps de traitement)."""
    university = resolve_university(request)
    form, context = _filter_context(request, university)
    qs = filtered_tickets(request, form, university)
    page_obj = paginate(request, qs, per_page=PAGE_SIZE)
    context.update(
        {
            "page_obj": page_obj,
            "rows": _annotate_processing(page_obj.object_list),
            "total_filtered": qs.count(),
            "status_choices": Ticket.Status.choices,
            "overdue_thresholds": metrics_service.thresholds(None, university)[:2],
        }
    )
    return render(request, "partials/admin/requests.html", context)


@console_required(*READ_PERMS)
def admin_requests_list(request):
    """Liste seule (rafraîchissement, sans perdre les filtres)."""
    university = resolve_university(request)
    form, context = _filter_context(request, university)
    qs = filtered_tickets(request, form, university)
    page_obj = paginate(request, qs, per_page=PAGE_SIZE)
    context.update(
        {
            "page_obj": page_obj,
            "rows": _annotate_processing(page_obj.object_list),
            "total_filtered": qs.count(),
            "has_filters": bool(form.active_filters()),
        }
    )
    return render(request, "partials/admin/requests_list.html", context)


def _load_ticket(request, university):
    from core_scolarite.services.scoping import parse_uuid

    pk = parse_uuid(request.GET.get("ticket") or request.POST.get("ticket"))
    if pk is None:
        return None
    qs = _scope_tickets(Ticket.objects.all(), university)
    return qs.filter(pk=pk).select_related(
        "student__user",
        "student__faculty",
        "student__department",
        "teacher__user",
        "teacher__faculty",
        "course__department",
        "problem_type",
    ).first()


@console_required(*READ_PERMS)
def admin_requests_detail(request):
    """Fiche détaillée en lecture seule : identité, statut, temps de traitement."""
    university = resolve_university(request)
    ticket = _load_ticket(request, university)
    if ticket is None:
        return json_error(_("Requête introuvable."), status=404)

    context = {
        "ticket": ticket,
        "processing": processing_time(ticket),
        "history": ticket.status_history.select_related("actor").order_by("-created_at"),
        "comments": ticket.comments.select_related("author").order_by("created_at"),
        "attachments": [
            {
                "name": attachment.file.name.split("/")[-1],
                "url": attachment.file.url,
                "label": str(attachment.config) if attachment.config_id else "",
            }
            for attachment in ticket.attachments.all()
        ],
        "status_choices": Ticket.Status.choices,
        "is_overdue": metrics_service.is_overdue(ticket, university),
        "is_blocked": metrics_service.is_blocked(ticket, university),
        "max_days": metrics_service.thresholds(ticket, university)[0],
    }
    return render(request, "partials/admin/request_detail.html", context)
