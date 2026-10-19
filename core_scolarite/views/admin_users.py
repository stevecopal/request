"""
C1 — Gestion des utilisateurs (console super-admin).

  GET  admin/users/                      liste paginée + filtres (fragment)
  GET  admin/users/modal/?pk=            modale d'édition d'un compte
  POST admin/users/modal/?pk=            enregistrement (identité, rôle, droits)
  POST admin/users/toggle/               activation / désactivation
  GET  admin/users/credentials/?pk=      modale d'émission d'accès
  POST admin/users/credentials/?pk=      mot de passe à usage unique (superuser)

Règles :
  * jamais de suppression de compte ici (désactivation douce uniquement) ;
  * émission d'accès, promotion/dégradation d'un compte administrateur et
    désactivation de son propre compte : `superuser_required` ;
  * chaque écriture est journalisée (`services.audit`).
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import console_required, superuser_required
from accounts.models import Faculty
from core_scolarite.forms import ROLE_ADMIN, ROLE_CHOICES, ROLE_NONE, ROLE_STUDENT, ROLE_TEACHER, AdminUserForm
from core_scolarite.services import audit as audit_service
from core_scolarite.services.credentials import issue_one_time_password
from core_scolarite.services.scoping import resolve_university

from .common import (
    form_error_json,
    json_error,
    json_ok,
    paginate,
    render_modal,
    scoped_object,
    toggle_is_active,
)

PERMS = ("auth.view_user", "auth.change_user", "auth.add_user")
SEARCH_FIELDS = ("username", "first_name", "last_name", "email")


def _role_of(user) -> str:
    if user.is_superuser:
        return ROLE_ADMIN
    if getattr(user, "teacher_profile", None) is not None:
        return ROLE_TEACHER
    if getattr(user, "student_profile", None) is not None:
        return ROLE_STUDENT
    return ROLE_NONE


def _placement_of(user) -> str:
    profile = getattr(user, "student_profile", None) or getattr(
        user, "teacher_profile", None
    )
    if profile is None:
        return "—"
    parts = []
    if profile.faculty_id:
        parts.append(profile.faculty.name)
    if profile.department_id:
        parts.append(profile.department.name)
    return " · ".join(parts) or "—"


def users_queryset(request, university=None):
    qs = User.objects.select_related(
        "student_profile__faculty",
        "student_profile__department",
        "teacher_profile__faculty",
        "teacher_profile__department",
    ).order_by("username")
    if university is not None:
        qs = qs.filter(
            Q(is_superuser=True)
            | Q(is_staff=True)
            | Q(student_profile__faculty__university=university)
            | Q(teacher_profile__faculty__university=university)
        )

    query = (request.GET.get("q") or "").strip()
    if query:
        condition = Q()
        for field in SEARCH_FIELDS:
            condition |= Q(**{f"{field}__icontains": query})
        qs = qs.filter(condition)

    role = request.GET.get("role") or ""
    if role == ROLE_ADMIN:
        qs = qs.filter(is_superuser=True)
    elif role == ROLE_TEACHER:
        qs = qs.filter(teacher_profile__isnull=False)
    elif role == ROLE_STUDENT:
        qs = qs.filter(student_profile__isnull=False)
    elif role == ROLE_NONE:
        qs = qs.filter(
            is_superuser=False,
            teacher_profile__isnull=True,
            student_profile__isnull=True,
        )

    status = request.GET.get("status") or ""
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    faculty_id = request.GET.get("faculty") or ""
    if faculty_id:
        qs = qs.filter(
            Q(student_profile__faculty_id=faculty_id)
            | Q(teacher_profile__faculty_id=faculty_id)
        )
    return qs.distinct()


@console_required(*PERMS)
def admin_users(request):
    """Fragment C1 : liste des comptes avec filtres et actions."""
    university = resolve_university(request)
    page_obj = paginate(request, users_queryset(request, university))
    role_labels = dict(ROLE_CHOICES)
    rows = []
    for user in page_obj.object_list:
        role = _role_of(user)
        rows.append(
            {
                "user": user,
                "role": role,
                "role_label": role_labels.get(role, role),
                "placement": _placement_of(user),
            }
        )
    faculties = Faculty.objects.filter(is_active=True)
    if university is not None:
        faculties = faculties.filter(university=university)
    active = {
        "q": request.GET.get("q", ""),
        "role": request.GET.get("role", ""),
        "status": request.GET.get("status", ""),
        "faculty": request.GET.get("faculty", ""),
    }
    context = {
        "page_obj": page_obj,
        "rows": rows,
        "faculties": faculties.order_by("name"),
        "active": active,
        "active_qs": "&".join(
            f"{key}={value}" for key, value in active.items() if value
        ),
        "has_filters": any(active.values()),
        "role_choices": ROLE_CHOICES,
        "is_superuser": request.user.is_superuser,
        "counts": {
            "total": User.objects.count(),
            "active": User.objects.filter(is_active=True).count(),
            "inactive": User.objects.filter(is_active=False).count(),
        },
    }
    return render(request, "partials/admin/users.html", context)


def _wire_cascade(form):
    """Cascade faculté → département (compatible admin_forms / admin_console)."""
    if "faculty" in form.fields and "department" in form.fields:
        form.fields["faculty"].widget.attrs.update(
            {
                "data-department-target": "#id_department",
                "data-departments-url": reverse("accounts:departments"),
            }
        )
        has_faculty = bool(
            form.fields["faculty"].initial or form.initial.get("faculty")
        )
        if not has_faculty:
            form.fields["department"].widget.attrs["disabled"] = "disabled"
    return form


@require_http_methods(["GET", "POST"])
@console_required("auth.change_user")
def admin_users_modal(request):
    """Édition d'un compte : identité, statut, rôle, rattachement, permissions."""
    university = resolve_university(request)
    target = scoped_object(
        User, request, scope=None, university=None, param="pk", required=True
    )
    if target is None:
        return json_error(_("Compte introuvable."), status=404)

    if request.method == "GET":
        form = _wire_cascade(AdminUserForm(user=target, university=university))
        return render_modal(
            request,
            form=form,
            title=_("Modifier le compte — %(name)s")
            % {"name": target.username},
            save_url=request.get_full_path(),
        )

    # Promotion en administrateur / action sur un compte admin → superuser.
    role = request.POST.get("role")
    if (target.is_superuser or role == ROLE_ADMIN) and not request.user.is_superuser:
        return json_error(
            _("La gestion des comptes administrateurs est réservée aux super-administrateurs."),
            status=403,
        )

    form = AdminUserForm(request.POST, user=target, university=university)
    form.actor = request.user  # garde-fous « je ne me retire pas mes droits ».
    if not form.is_valid():
        return form_error_json(form)

    changes = form.save()
    audit_service.record(
        request,
        audit_service.AuditLog.Action.UPDATE,
        obj=target,
        changes=changes,
        university=university,
    )
    return json_ok(_("Compte mis à jour."))


@require_POST
@console_required("auth.change_user")
def admin_users_toggle(request):
    """Active/désactive un compte (désactivation douce, jamais de suppression)."""
    target = scoped_object(User, request, scope=None, university=None, param="pk")
    if target is None:
        return json_error(_("Compte introuvable."), status=404)
    if target == request.user:
        return json_error(_("Vous ne pouvez pas désactiver votre propre compte."))
    if target.is_superuser and not request.user.is_superuser:
        return json_error(
            _("La gestion des comptes administrateurs est réservée aux super-administrateurs."),
            status=403,
        )
    return toggle_is_active(
        request,
        model=User,
        scope=None,
        university=None,
        label=_("Compte %(name)s") % {"name": target.username},
    )


@require_http_methods(["GET", "POST"])
@superuser_required
def admin_users_credentials(request):
    """Émission d'un mot de passe à usage unique (affiché une seule fois)."""
    target = scoped_object(User, request, scope=None, university=None, param="pk")
    if target is None:
        return json_error(_("Compte introuvable."), status=404)

    if request.method == "GET":
        return render_modal(
            request,
            form=None,
            title=_("Émettre un accès — %(name)s") % {"name": target.username},
            save_url=request.get_full_path(),
            extra={"credential_user": target},
        )

    password = issue_one_time_password(target)
    audit_service.record(
        request,
        audit_service.AuditLog.Action.CREDENTIALS,
        obj=target,
        changes={"password": "regenerated"},
    )
    # Le mot de passe n'est ni journalisé ni conservé : renvoyé une seule fois.
    return json_ok(
        _("Mot de passe réémis. Transmettez-le hors canal, il n'affichera pas deux fois."),
        username=target.username,
        password=password,
    )
