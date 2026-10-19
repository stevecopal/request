"""
C3 — Suivi central des requêtes (console super-admin).

  GET  admin/requests/             filtres + liste + panneau de détail (fragment)
  GET  admin/requests/list/        liste seule (rafraîchissement)
  GET  admin/requests/detail/?ticket=…   fiche détaillée + actions
  POST admin/requests/assign/      affectation d'un enseignant
  POST admin/requests/status/      transition de statut (moteur de statuts)

Droits : consultation = `tickets.view_ticket` (+ superuser), actions =
`tickets.change_ticket`. La transition passe par `apply_status` (verrouillage
concurrence + historique) — jamais de mise à jour SQL directe du statut.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.decorators import console_required
from accounts.models import Faculty, Teacher
from core_scolarite.forms import AdminRequestFilterForm
from core_scolarite.services import audit as audit_service
from core_scolarite.services import metrics as metrics_service
from core_scolarite.services.scoping import resolve_university
from tickets.models import Ticket, TicketStatusHistory
from tickets.services.status_machine import ALLOWED_TRANSITIONS, StatusTransitionError, apply_status

from .common import json_error, json_ok, paginate

READ_PERMS = ("tickets.view_ticket", "tickets.change_ticket")
WRITE_PERMS = ("tickets.change_ticket",)

STATUS_ACTION_LABELS = {
    Ticket.Status.RECEIVED: _("Acquitter"),
    Ticket.Status.PROCESSING: _("Prendre en charge"),
    Ticket.Status.RESOLVED: _("Valider"),
    Ticket.Status.REJECTED: _("Refuser"),
    Ticket.Status.MORE_INFO: _("Demander des infos"),
}

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


@console_required(*READ_PERMS)
def admin_requests(request):
    """Fragment C3 : filtres, liste paginée et zone de détail."""
    university = resolve_university(request)
    form, context = _filter_context(request, university)
    qs = filtered_tickets(request, form, university)
    page_obj = paginate(request, qs, per_page=PAGE_SIZE)
    context.update(
        {
            "page_obj": page_obj,
            "rows": page_obj.object_list,
            "total_filtered": qs.count(),
            "status_choices": Ticket.Status.choices,
            "overdue_thresholds": metrics_service.thresholds(None, university)[:2],
        }
    )
    return render(request, "partials/admin/requests.html", context)


@console_required(*READ_PERMS)
def admin_requests_list(request):
    """Liste seule (rafraîchissement après action, sans perdre les filtres)."""
    university = resolve_university(request)
    form, context = _filter_context(request, university)
    qs = filtered_tickets(request, form, university)
    page_obj = paginate(request, qs, per_page=PAGE_SIZE)
    context.update(
        {
            "page_obj": page_obj,
            "rows": page_obj.object_list,
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
    """Fiche détaillée : identité, historique, actions d'affectation/statut."""
    university = resolve_university(request)
    ticket = _load_ticket(request, university)
    if ticket is None:
        return json_error(_("Requête introuvable."), status=404)

    teachers = Teacher.objects.filter(user__is_active=True).select_related(
        "user", "faculty"
    )
    if university is not None:
        teachers = teachers.filter(faculty__university=university)
    teachers = teachers.order_by("user__last_name", "user__first_name")

    from django.conf import settings as django_settings

    actions = []
    for status in ALLOWED_TRANSITIONS.get(ticket.status, []):
        if status == Ticket.Status.MORE_INFO and not django_settings.ENABLE_TEACHER_MORE_INFO:
            continue
        actions.append(
            {
                "status": status,
                "label": STATUS_ACTION_LABELS.get(
                    status, _("Passer à %s") % dict(Ticket.Status.choices).get(status, status)
                ),
                "needs_reason": status == Ticket.Status.REJECTED,
                "needs_question": status == Ticket.Status.MORE_INFO,
            }
        )

    context = {
        "ticket": ticket,
        "actions": actions,
        "teachers": teachers,
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


@require_POST
@console_required(*WRITE_PERMS)
def admin_requests_assign(request):
    """Affecte (ou réaffecte) un enseignant — contrôle périmètre serveur."""
    university = resolve_university(request)
    ticket = _load_ticket(request, university)
    if ticket is None:
        return json_error(_("Requête introuvable."), status=404)

    from core_scolarite.services.scoping import parse_uuid

    teacher_id = parse_uuid(request.POST.get("teacher_id"))
    if teacher_id is None:
        return json_error(_("Enseignant manquant."))
    teachers = Teacher.objects.select_related("faculty", "user")
    if university is not None:
        teachers = teachers.filter(faculty__university=university)
    teacher = teachers.filter(pk=teacher_id).first()
    if teacher is None:
        return json_error(
            _("Enseignant introuvable hors du périmètre de l'université."), status=404
        )

    previous = ticket.teacher_id
    if previous == teacher.pk:
        return json_ok(_("Affectation inchangée."), unchanged=True)

    ticket.teacher = teacher
    ticket.save(update_fields=["teacher", "updated_at"])
    audit_service.record(
        request,
        audit_service.AuditLog.Action.UPDATE,
        obj=ticket,
        changes={"teacher": {"from": str(previous), "to": str(teacher.pk)}},
        university=university,
    )
    return json_ok(
        _("Requête affectée à %(name)s.")
        % {"name": teacher.user.get_full_name() or teacher.user.username}
    )


@require_POST
@console_required(*WRITE_PERMS)
def admin_requests_status(request):
    """Transition de statut administrative (moteur + historique + audit)."""
    university = resolve_university(request)
    ticket = _load_ticket(request, university)
    if ticket is None:
        return json_error(_("Requête introuvable."), status=404)

    new_status = request.POST.get("status") or ""
    # Une seule zone de note côté UI : motif de refus OU question selon cible.
    note = (
        request.POST.get("note")
        or request.POST.get("rejection_reason")
        or request.POST.get("more_info_request")
        or ""
    ).strip()
    reason = note if new_status == Ticket.Status.REJECTED else None
    question = note if new_status == Ticket.Status.MORE_INFO else None
    if new_status not in dict(Ticket.Status.choices):
        return json_error(_("Statut inconnu."))

    try:
        apply_status(
            ticket,
            new_status,
            reason=reason,
            actor=request.user,
            actor_role=TicketStatusHistory.ActorRole.SYSTEM,
            note=note,
            more_info_request=question,
        )
    except StatusTransitionError as exc:
        return json_error(exc.message, status=400, errors=exc.field_errors)

    audit_service.record(
        request,
        audit_service.AuditLog.Action.TRANSITION,
        obj=ticket,
        changes={"status": {"to": new_status}},
        university=university,
    )
    return json_ok(
        _("Statut mis à jour : %s.") % ticket.get_status_display(),
        status_label=ticket.status_label,
    )
