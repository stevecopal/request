"""
C6 — Sécurité & audit (console super-admin).

  GET  admin/security/                 journal + incidents + sessions (fragment)
  GET  admin/security/incident/modal/  modale de signalement d'incident
  POST admin/security/incident/modal/  enregistrement du signalement
  POST admin/security/event/resolve/   clôture d'un événement technique
  POST admin/security/session/revoke/  révocation d'une session (superuser)

Journal d'audit : immuable (aucune écriture depuis cet écran, lecture seule).
Sessions : révocation immédiate via suppression de la ligne `django_session`.
Erreurs système : alimentées automatiquement par
`core_scolarite.logging_handler.DatabaseLogHandler` (erreurs Django) ou
signalement manuel d'un administrateur.
"""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from urllib.parse import urlencode

from accounts.decorators import console_required, superuser_required
from core_scolarite.forms import IncidentReportForm
from core_scolarite.models import AuditLog, TechnicalEvent
from core_scolarite.services import audit as audit_service
from core_scolarite.services.scoping import parse_uuid, resolve_university

from .common import (
    form_error_json,
    json_error,
    json_ok,
    paginate,
    render_modal,
)

PERMS = ("core_scolarite.view_auditlog", "core_scolarite.change_technicalevent")

AUDIT_PAGE = 20
EVENT_PAGE = 20
SESSION_PAGE = 20


def _audit_queryset(request, university):
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    if university is not None:
        qs = qs.filter(Q(university=university) | Q(university__isnull=True))
    action = request.GET.get("action") or ""
    if action:
        qs = qs.filter(action=action)
    query = (request.GET.get("q") or "").strip()
    if query:
        qs = qs.filter(
            Q(actor__username__icontains=query)
            | Q(object_repr__icontains=query)
            | Q(model_label__icontains=query)
        )
    date_from = request.GET.get("date_from") or ""
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = request.GET.get("date_to") or ""
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def _event_queryset(request):
    qs = TechnicalEvent.objects.order_by("-created_at")
    level = request.GET.get("level") or ""
    if level in TechnicalEvent.Level.values:
        qs = qs.filter(level=level)
    state = request.GET.get("state") or ""
    if state == "open":
        qs = qs.filter(is_resolved=False)
    elif state == "resolved":
        qs = qs.filter(is_resolved=True)
    return qs


def _session_rows(page, viewer_id: str | None):
    """Décode les sessions actives (utilisateur résolu en masse)."""
    from django.contrib.auth.models import User

    sessions = list(page.object_list)
    user_ids = []
    decoded = []
    for session in sessions:
        try:
            data = session.get_decoded()
        except Exception:  # noqa: BLE001 — session corrompue : affichée telle quelle.
            data = {}
        user_id = data.get("_auth_user_id")
        if user_id:
            user_ids.append(user_id)
        decoded.append({"session": session, "user_id": user_id})
    users = User.objects.in_bulk([uid for uid in user_ids if uid])
    rows = []
    for item in decoded:
        user = users.get(item["user_id"])
        rows.append(
            {
                "session": item["session"],
                "key_prefix": f"{item['session'].session_key[:12]}…",
                "user": user,
                "username": user.username if user else _("Compte supprimé"),
                "last_login": user.last_login if user else None,
                "is_self": bool(item["user_id"] and item["user_id"] == viewer_id),
            }
        )
    return rows


@console_required(*PERMS)
def admin_security(request):
    """Fragment C6 : journal d'audit, erreurs/incidents et sessions actives."""
    university = resolve_university(request)

    audit_page = paginate(
        request, _audit_queryset(request, university), per_page=AUDIT_PAGE, param="audit_page"
    )
    event_page = paginate(
        request, _event_queryset(request), per_page=EVENT_PAGE, param="event_page"
    )
    session_page = paginate(
        request,
        Session.objects.filter(expire_date__gte=timezone.now()).order_by("-expire_date"),
        per_page=SESSION_PAGE,
        param="session_page",
    )
    rows = _session_rows(session_page, session_user_id(request))

    context = {
        "audit_page": audit_page,
        "event_page": event_page,
        "session_page": session_page,
        "session_rows": rows,
        "audit_actions": AuditLog.Action.choices,
        "levels": TechnicalEvent.Level.choices,
        "active": {
            "action": request.GET.get("action", ""),
            "q": request.GET.get("q", ""),
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "level": request.GET.get("level", ""),
            "state": request.GET.get("state", ""),
        },
        "open_events": TechnicalEvent.objects.filter(is_resolved=False).count(),
        "can_revoke": request.user.is_superuser,
        # Filtres conservés lors de la pagination des trois blocs.
        "page_qs": urlencode(
            {
                key: value
                for key, value in request.GET.items()
                if key not in ("audit_page", "event_page", "session_page") and value
            }
        ),
    }
    return render(request, "partials/admin/security.html", context)


def session_user_id(request) -> str | None:
    """Identifiant utilisateur porté par la session courante."""
    try:
        return request.session.get("_auth_user_id")
    except Exception:  # noqa: BLE001
        return None


@require_http_methods(["GET", "POST"])
@console_required("core_scolarite.change_technicalevent")
def admin_security_incident_modal(request):
    """Signalement manuel d'un incident technique (C6)."""
    if request.method == "GET":
        return render_modal(
            request,
            form=IncidentReportForm(),
            title=_("Signaler un incident"),
            save_url=request.get_full_path(),
        )

    form = IncidentReportForm(request.POST)
    if not form.is_valid():
        return form_error_json(form)
    event = TechnicalEvent.objects.create(
        level=form.cleaned_data["level"],
        source=TechnicalEvent.Source.MANUAL,
        message=form.cleaned_data["message"],
        reported_by=request.user,
    )
    audit_service.record(
        request,
        audit_service.AuditLog.Action.CREATE,
        obj=event,
        university=resolve_university(request),
    )
    return json_ok(_("Incident signalé."))


@require_POST
@console_required("core_scolarite.change_technicalevent")
def admin_security_event_resolve(request):
    """Marque un événement technique comme résolu (traitement manuel)."""
    pk = parse_uuid(request.POST.get("pk"))
    if pk is None:
        return json_error(_("Paramètre « pk » manquant."))
    event = TechnicalEvent.objects.filter(pk=pk).first()
    if event is None:
        return json_error(_("Événement introuvable."), status=404)
    if event.is_resolved:
        return json_ok(_("Événement déjà résolu."), unchanged=True)
    event.is_resolved = True
    event.resolved_at = timezone.now()
    event.resolved_by = request.user
    event.save(update_fields=["is_resolved", "resolved_at", "resolved_by"])
    audit_service.record(
        request,
        audit_service.AuditLog.Action.UPDATE,
        obj=event,
        changes={"is_resolved": {"from": False, "to": True}},
        university=resolve_university(request),
    )
    return json_ok(_("Événement marqué comme résolu."))


@require_POST
@superuser_required
def admin_security_session_revoke(request):
    """Révoque immédiatement une session (déconnexion forcée)."""
    session_key = (request.POST.get("session_key") or "").strip()
    if not session_key:
        return json_error(_("Clé de session manquante."))
    if session_key == request.session.session_key:
        return json_error(
            _("Vous ne pouvez pas révoquer votre propre session depuis cet écran.")
        )
    deleted, _ = Session.objects.filter(session_key=session_key).delete()
    if not deleted:
        return json_error(_("Session introuvable ou déjà expirée."), status=404)
    audit_service.record(
        request,
        audit_service.AuditLog.Action.DELETE,
        model_label="sessions.Session",
        object_pk=session_key[:64],
        object_repr=f"session {session_key[:12]}…",
        university=resolve_university(request),
    )
    return json_ok(_("Session révoquée."))
