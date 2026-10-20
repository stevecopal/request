"""
C2 — Organisation universitaire (console super-admin).

  GET  admin/structure/                         onglets + listes (fragment)
  GET  admin/structure/modal/<kind>/            modale de création/édition
  POST admin/structure/modal/<kind>/            enregistrement
  POST admin/structure/toggle/<kind>/           activation / désactivation

Kinds : `faculty`, `department`, `program`, `service`, `assignment`
(affectation enseignant-cours), `member` (membre d'un service).

Aucune suppression dans ce module : désactivation douce uniquement
(l'historique des requêtes prime toujours).
"""

from __future__ import annotations

from django.db.models import Count, Q
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import console_required
from accounts.models import Department, Faculty, Program
from accounts.spa import spa_page
from core_scolarite.forms import (
    CourseAssignmentForm,
    DepartmentForm,
    FacultyForm,
    ProgramForm,
    ServiceForm,
    ServiceMemberForm,
)
from core_scolarite.models import CourseAssignment, Service, ServiceAssignment
from core_scolarite.services import audit as audit_service
from core_scolarite.services.scoping import resolve_university

from .common import (
    form_error_json,
    json_error,
    json_ok,
    render_modal,
    save_model_form,
    scoped_object,
    toggle_is_active,
)

PERMS = (
    "accounts.change_faculty",
    "accounts.change_department",
    "accounts.change_program",
    "core_scolarite.change_service",
)

# Registre des kinds C2 : portée université + formulaire + libellés.
KINDS = {
    "faculty": {
        "model": Faculty,
        "form": FacultyForm,
        "scope": "university",
        "label": _("Faculté"),
        "plural": _("Facultés"),
        "set_university": True,
        "order": ["name"],
    },
    "department": {
        "model": Department,
        "form": DepartmentForm,
        "scope": "faculty__university",
        "label": _("Département"),
        "plural": _("Départements"),
        "order": ["faculty__name", "name"],
    },
    "program": {
        "model": Program,
        "form": ProgramForm,
        "scope": "department__faculty__university",
        "label": _("Filière"),
        "plural": _("Filières"),
        "order": ["name"],
    },
    "service": {
        "model": Service,
        "form": ServiceForm,
        "scope": "university",
        "label": _("Service"),
        "plural": _("Services"),
        "set_university": True,
        "order": ["name"],
    },
    "assignment": {
        "model": CourseAssignment,
        "form": CourseAssignmentForm,
        "scope": "department__faculty__university",
        "label": _("Affectation"),
        "plural": _("Affectations"),
        "order": ["-created_at"],
    },
    "member": {
        "model": ServiceAssignment,
        "form": ServiceMemberForm,
        "scope": "service__university",
        "label": _("Membre"),
        "plural": _("Membres"),
        "order": ["service__name", "user__last_name"],
    },
}

LIST_LIMIT = 100


def _base_queryset(kind: str, university):
    """Queryset du kind dans le périmètre université (sans agrégation)."""
    spec = KINDS[kind]
    qs = spec["model"]._default_manager.all()
    if university is not None:
        qs = qs.filter(**{spec["scope"]: university})
    return qs


def _scoped_queryset(kind: str, university):
    """Queryset listable : périmètre + agrégations de comptes (anti N+1)."""
    qs = _base_queryset(kind, university)
    if kind == "faculty":
        qs = qs.annotate(
            n_departments=Count("departments", filter=Q(departments__is_active=True))
        )
    elif kind == "department":
        qs = qs.annotate(
            n_programs=Count("programs", filter=Q(programs__is_active=True))
        )
    elif kind == "service":
        qs = qs.annotate(
            n_members=Count("assignments", filter=Q(assignments__is_active=True)),
            n_types=Count("problem_types", filter=Q(problem_types__is_active=True)),
        )
    return qs.select_related()


def _rows(kind: str, university) -> list[dict]:
    """Lignes unifiées (titre, sous-titre, méta) rendues par le template."""
    spec = KINDS[kind]
    qs = _scoped_queryset(kind, university).order_by(*spec["order"])[:LIST_LIMIT]

    rows = []
    for obj in qs:
        row = {
            "pk": str(obj.pk),
            "title": "",
            "subtitle": "",
            "meta": [],
            "is_active": bool(getattr(obj, "is_active", True)),
        }
        if kind == "faculty":
            row["title"] = obj.name
            row["meta"] = [
                *([obj.code] if obj.code else []),
                _("%(n)s départements") % {"n": obj.n_departments},
            ]
        elif kind == "department":
            row["title"] = obj.name
            row["subtitle"] = obj.faculty.name
            row["meta"] = [_("%(n)s filières") % {"n": obj.n_programs}]
        elif kind == "program":
            row["title"] = f"{obj.code} — {obj.name}"
            row["subtitle"] = f"{obj.get_level_display()} · {obj.department.name}"
        elif kind == "service":
            row["title"] = obj.name
            row["subtitle"] = obj.contact_email or _("Pas d'email de contact")
            row["meta"] = [
                _("%(n)s membres") % {"n": obj.n_members},
                _("%(n)s catégories") % {"n": obj.n_types},
            ]
        elif kind == "assignment":
            row["title"] = f"{obj.course.code} — {obj.course.name}"
            row["subtitle"] = (
                f"{obj.teacher.user.get_full_name() or obj.teacher.user.username}"
                f" · {obj.academic_year.code}"
            )
            row["meta"] = [obj.department.name]
        elif kind == "member":
            user = obj.user
            row["title"] = user.get_full_name() or user.username
            row["subtitle"] = obj.service.name
            row["meta"] = [obj.get_role_display(), user.username]
        rows.append(row)
    return rows


@spa_page
@console_required(*PERMS)
def admin_organization(request):
    """Fragment C2 : navigation par onglets + liste du kind courant."""
    university = resolve_university(request)
    tab = request.GET.get("tab") or "faculty"
    if tab not in KINDS:
        tab = "faculty"
    context = {
        "tab": tab,
        "kinds": [
            {
                "key": key,
                "label": KINDS[key]["plural"],
                "count": _base_queryset(key, university).count(),
            }
            for key in KINDS
        ],
        "rows": _rows(tab, university),
        "kind_spec": KINDS[tab],
        "kind_key": tab,
        "services": (
            Service.objects.filter(university=university).order_by("name")
            if university is not None
            else Service.objects.all().order_by("name")
        ),
    }
    return render(request, "partials/admin/organization.html", context)


@require_http_methods(["GET", "POST"])
@console_required(*PERMS)
def admin_organization_modal(request, kind: str):
    """Création / édition d'un objet d'organisation (formulaire générique)."""
    if kind not in KINDS:
        return json_error(_("Type d'objet inconnu."), status=404)
    spec = KINDS[kind]
    university = resolve_university(request)
    instance = None
    if request.GET.get("pk") or request.POST.get("pk"):
        instance = scoped_object(
            spec["model"], request, scope=spec["scope"], university=university
        )
        if instance is None:
            return json_error(_("Objet introuvable."), status=404)

    # Membre : service porteur passé en paramètre de la modale.
    service = None
    if kind == "member":
        service = scoped_object(
            Service,
            request,
            scope="university",
            university=university,
            param="service",
        )
        if service is None:
            return json_error(_("Service introuvable."), status=404)

    form_class = spec["form"]
    form_kwargs = {"university": university}
    if kind == "member":
        form = form_class(request.POST or None, **form_kwargs)
    else:
        data = request.POST if request.method == "POST" else None
        if instance is not None:
            form = form_class(data, instance=instance, **form_kwargs)
        else:
            form = form_class(data, **form_kwargs)
            if spec.get("set_university"):
                # Université de travail appliquée côté serveur (jamais côté client).
                form.instance.university = university

    if request.method == "GET":
        title = spec["label"]
        if instance is not None:
            title = _("Modifier — %(name)s") % {"name": str(instance)}
        return render_modal(
            request, form=form, title=title, save_url=request.get_full_path()
        )

    # --- POST : member est un formulaire simple (pas de ModelForm) --- #
    if kind == "member":
        if not form.is_valid():
            return form_error_json(form)
        user = form.cleaned_data["user"]
        if ServiceAssignment.objects.filter(service=service, user=user).exists():
            return form_error_json(
                form, message=_("Cette personne est déjà membre du service.")
            )
        assignment = ServiceAssignment.objects.create(
            service=service, user=user, role=form.cleaned_data["role"]
        )
        audit_service.record(
            request,
            audit_service.AuditLog.Action.CREATE,
            obj=assignment,
            university=university,
        )
        return json_ok(_("Membre ajouté au service."))

    return save_model_form(
        request,
        form,
        message=_("%(label)s enregistré(e).") % {"label": spec["label"]},
        university=university,
        scope=spec["scope"],
    )


@require_POST
@console_required(*PERMS)
def admin_organization_toggle(request, kind: str):
    """Active/désactive un objet d'organisation (jamais de suppression)."""
    if kind not in KINDS:
        return json_error(_("Type d'objet inconnu."), status=404)
    spec = KINDS[kind]
    university = resolve_university(request)
    return toggle_is_active(
        request,
        model=spec["model"],
        scope=spec["scope"],
        university=university,
        label=spec["label"],
    )
