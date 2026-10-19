"""
C4 — Configuration du workflow (console super-admin).

  GET  admin/workflow/                    onglets + listes (fragment)
  GET  admin/workflow/modal/<kind>/       modale de création/édition
  POST admin/workflow/modal/<kind>/       enregistrement
  POST admin/workflow/toggle/<kind>/      activation / désactivation
  POST admin/workflow/delete/<kind>/      suppression (config uniquement)

Onglets : `types` (catégories), `fields` (champs), `attachments` (pièces
jointes), `rules` (règles conditionnelles), `courses` (cours requis),
`sla` (délais), `reminders` (relances), `decisions` (qui décide).

Les onglets liés à une catégorie exigent `?type=<uuid>` — contrôle objet
contre le périmètre université à chaque lecture **et** chaque écriture.
Une catégorie utilisée par des requêtes n'est jamais supprimée (PROTECT +
désactivation douce).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import console_required
from accounts.spa import spa_page
from core_scolarite.forms import (
    AttachmentConfigConsoleForm,
    ConditionalRuleConsoleForm,
    DecisionRuleConsoleForm,
    FormFieldConsoleForm,
    ProblemTypeConsoleForm,
    ReminderPolicyConsoleForm,
    RequiredCourseConsoleForm,
    SlaPolicyConsoleForm,
)
from core_scolarite.models import (
    AttachmentConfig,
    ConditionalRule,
    DecisionRule,
    FormField,
    ProblemType,
    ProblemTypeRequiredCourse,
    ReminderPolicy,
    SlaPolicy,
)
from core_scolarite.services import audit as audit_service
from core_scolarite.services.scoping import parse_uuid, resolve_university
from django.db.models.deletion import ProtectedError, RestrictedError

from .common import (
    form_error_json,
    json_error,
    json_ok,
    render_modal,
    save_model_form,
    scoped_object,
)

PERMS = ("core_scolarite.change_problemtype", "core_scolarite.view_problemtype")

TABS = (
    ("types", _("Catégories")),
    ("fields", _("Champs")),
    ("attachments", _("Pièces jointes")),
    ("rules", _("Règles conditionnelles")),
    ("courses", _("Cours requis")),
    ("sla", _("Délais (SLA)")),
    ("reminders", _("Relances")),
    ("decisions", _("Décisions")),
)
TYPE_DEPENDENT_TABS = {"fields", "attachments", "rules", "courses", "decisions"}

# kinds de modale liés à une catégorie (scoped via `problem_type`).
TYPE_KINDS = {
    "field": {
        "model": FormField,
        "form": FormFieldConsoleForm,
        "label": _("Champ"),
    },
    "attachment": {
        "model": AttachmentConfig,
        "form": AttachmentConfigConsoleForm,
        "label": _("Pièce jointe"),
    },
    "rule": {
        "model": ConditionalRule,
        "form": ConditionalRuleConsoleForm,
        "label": _("Règle conditionnelle"),
    },
    "decision": {
        "model": DecisionRule,
        "form": DecisionRuleConsoleForm,
        "label": _("Règle de décision"),
    },
    "course": {
        "model": ProblemTypeRequiredCourse,
        "form": RequiredCourseConsoleForm,
        "label": _("Cours requis"),
        "plain_form": True,
    },
    "type": {
        "model": ProblemType,
        "form": ProblemTypeConsoleForm,
        "label": _("Catégorie"),
        "university_nullable": True,
        "set_university": True,
    },
    "sla": {
        "model": SlaPolicy,
        "form": SlaPolicyConsoleForm,
        "label": _("Règle de délai"),
        "university_nullable": True,
        "set_university": True,
    },
    "reminder": {
        "model": ReminderPolicy,
        "form": ReminderPolicyConsoleForm,
        "label": _("Relance"),
        "university_nullable": True,
        "set_university": True,
    },
}

TOGGLE_KINDS = ("type", "field", "decision", "sla", "reminder")
DELETE_KINDS = ("field", "attachment", "rule", "course", "decision")


def _scoped_types(university):
    qs = ProblemType.objects.all()
    if university is not None:
        qs = qs.filter(Q(university=university) | Q(university__isnull=True))
    return qs.select_related("service").order_by("position", "name")


def _current_type(request, university):
    """Catégorie de l'onglet courant (contrôle objet, jamais cru du client)."""
    pk = parse_uuid(request.GET.get("type") or request.POST.get("type"))
    if pk is None:
        return None
    return _scoped_types(university).filter(pk=pk).first()


def _in_type_scope(obj, university) -> bool:
    """L'objet dépend d'une catégorie appartenant au périmètre ?"""
    problem_type = getattr(obj, "problem_type", None)
    if problem_type is None:
        return False
    if university is None:
        return True
    return problem_type.university_id in (None, university.pk)


def _in_university_scope(spec, obj, university) -> bool:
    if not spec.get("university_nullable") or university is None:
        return True
    return obj.university_id in (None, university.pk)


# --------------------------------------------------------------------------- #
# Listes (lignes unifiées rendues par le template)
# --------------------------------------------------------------------------- #

def _row(pk, title, subtitle="", meta=None, is_active=True):
    return {
        "pk": str(pk),
        "title": title,
        "subtitle": subtitle,
        "meta": meta or [],
        "is_active": is_active,
    }


def _tab_rows(tab, university, current_type):
    if tab == "types":
        return [
            _row(
                t.pk,
                t.name,
                t.service.name if t.service_id else _("Aucun service"),
                [
                    _("Oblige un cours") if t.requires_course else _("Cours libre"),
                    _("%(n)s champs") % {"n": t.fields.count()},
                ],
                t.is_active,
            )
            for t in _scoped_types(university)
        ]
    if tab == "sla":
        qs = SlaPolicy.objects.select_related("problem_type")
        if university is not None:
            qs = qs.filter(Q(university=university) | Q(university__isnull=True))
        return [
            _row(
                p.pk,
                p.name,
                p.problem_type.name
                if p.problem_type_id
                else _("Toutes les requêtes du périmètre"),
                [
                    _("%(a)s j de traitement / %(b)s j de blocage")
                    % {"a": p.max_days, "b": p.blocked_after_days},
                    p.statuses,
                ],
                p.is_active,
            )
            for p in qs.order_by("name")
        ]
    if tab == "reminders":
        qs = ReminderPolicy.objects.all()
        if university is not None:
            qs = qs.filter(Q(university=university) | Q(university__isnull=True))
        return [
            _row(
                p.pk,
                p.name,
                _("Destinataire : %(role)s") % {"role": p.get_target_role_display()},
                [_("%(n)s jours") % {"n": p.delay_days}],
                p.is_active,
            )
            for p in qs.order_by("name")
        ]

    if current_type is None:
        return []
    if tab == "fields":
        return [
            _row(
                f.pk,
                f.label,
                f"{f.key} · {f.get_field_type_display()}",
                [
                    _("Obligatoire") if f.is_required else _("Facultatif"),
                    _("ordre %d") % f.position,
                ],
                f.is_active,
            )
            for f in current_type.fields.order_by("position", "id")
        ]
    if tab == "attachments":
        return [
            _row(
                a.pk,
                a.label,
                a.allowed_types,
                [
                    _("Obligatoire") if a.is_required else _("Facultatif"),
                    _("%(n)s Mo") % {"n": a.max_size_mb},
                ],
                True,
            )
            for a in current_type.required_attachments.all()
        ]
    if tab == "rules":
        rules = ConditionalRule.objects.filter(
            field__problem_type=current_type
        ).select_related("field", "depends_on")
        return [
            _row(
                r.pk,
                _("« %(field)s » %(op)s « %(value)s » → %(action)s")
                % {
                    "field": r.field.label,
                    "op": r.get_operator_display(),
                    "value": r.value or _("renseigné"),
                    "action": r.get_action_display(),
                },
                _("Dépend de « %(dep)s »") % {"dep": r.depends_on.label},
                [],
                True,
            )
            for r in rules
        ]
    if tab == "courses":
        return [
            _row(
                rc.pk,
                f"{rc.course.code} — {rc.course.name}",
                rc.course.department.name if rc.course.department_id else "",
                [_("Obligatoire") if rc.is_required else _("Conseillé")],
                True,
            )
            for rc in current_type.required_courses.select_related(
                "course__department"
            )
        ]
    if tab == "decisions":
        return [
            _row(
                r.pk,
                _("%(action)s — %(scope)s")
                % {"action": r.get_action_display(), "scope": r.get_scope_display()},
                _("ordre %d") % r.position,
                [],
                r.is_active,
            )
            for r in current_type.decision_rules.all()
        ]
    return []


TAB_KINDS = {
    "types": "type",
    "fields": "field",
    "attachments": "attachment",
    "rules": "rule",
    "courses": "course",
    "sla": "sla",
    "reminders": "reminder",
    "decisions": "decision",
}


@spa_page
@console_required(*PERMS)
def admin_workflow(request):
    """Fragment C4 : onglets de configuration + liste du kind courant."""
    university = resolve_university(request)
    tab = request.GET.get("tab") or "types"
    if tab not in dict(TABS):
        tab = "types"
    current_type = None
    if tab in TYPE_DEPENDENT_TABS:
        current_type = _current_type(request, university)
        if current_type is None:
            current_type = _scoped_types(university).first()

    counts = {
        "types": _scoped_types(university).count(),
        "sla": (
            SlaPolicy.objects.filter(Q(university=university) | Q(university__isnull=True)).count()
            if university is not None
            else SlaPolicy.objects.count()
        ),
        "reminders": (
            ReminderPolicy.objects.filter(
                Q(university=university) | Q(university__isnull=True)
            ).count()
            if university is not None
            else ReminderPolicy.objects.count()
        ),
    }
    context = {
        "tab": tab,
        "kind": TAB_KINDS[tab],
        "tabs": [{"key": key, "label": label, "count": counts.get(key)} for key, label in TABS],
        "type_dependent": tab in TYPE_DEPENDENT_TABS,
        "current_type": current_type,
        "type_choices": _scoped_types(university),
        "rows": _tab_rows(tab, university, current_type),
        "can_toggle": tab in ("types", "fields", "decisions", "sla", "reminders"),
        "can_delete": tab in ("fields", "attachments", "rules", "courses", "decisions"),
        "show_active": tab in ("types", "fields", "decisions", "sla", "reminders"),
        "has_types": _scoped_types(university).exists(),
    }
    return render(request, "partials/admin/workflow.html", context)


# --------------------------------------------------------------------------- #
# Modales (création / édition)
# --------------------------------------------------------------------------- #

@require_http_methods(["GET", "POST"])
@console_required(*PERMS)
def admin_workflow_modal(request, kind: str):
    spec = TYPE_KINDS.get(kind)
    if spec is None:
        return json_error(_("Type de configuration inconnu."), status=404)
    university = resolve_university(request)
    needs_type = kind in ("field", "attachment", "rule", "course", "decision")

    # --- résolution de la catégorie (lecture ou écriture) --- #
    problem_type = None
    if needs_type:
        pk = parse_uuid(request.GET.get("pk") or request.POST.get("pk"))
        instance = None
        if pk is not None:
            instance = spec["model"]._default_manager.filter(pk=pk).first()
            if instance is None:
                return json_error(_("Objet introuvable."), status=404)
            if not _in_type_scope(instance, university):
                return json_error(
                    _("Cet objet appartient à une autre université."), status=403
                )
            problem_type = instance.problem_type
        else:
            problem_type = _current_type(request, university)
            if problem_type is None:
                return json_error(_("Catégorie de requête requise."), status=400)
    else:
        instance = None
        if request.GET.get("pk") or request.POST.get("pk"):
            instance = scoped_object(
                spec["model"],
                request,
                scope=None,
                university=university,
            )
            if instance is None:
                return json_error(_("Objet introuvable."), status=404)
            if not _in_university_scope(spec, instance, university):
                return json_error(
                    _("Cet objet appartient à une autre université."), status=403
                )

    # --- construction du formulaire --- #
    form_class = spec["form"]
    data = request.POST if request.method == "POST" else None
    if kind == "type":
        form = form_class(data, instance=instance, university=university)
        if instance is None:
            form.instance.university = university  # périmètre serveur
    elif kind in ("sla", "reminder"):
        form = form_class(data, instance=instance, university=university)
        if instance is None:
            form.instance.university = university
    elif spec.get("plain_form"):
        form = form_class(data, problem_type=problem_type)
    else:
        form = form_class(data, instance=instance, problem_type=problem_type)

    if request.method == "GET":
        title = spec["label"]
        if instance is not None:
            title = _("Modifier — %(name)s") % {"name": str(instance)}
        save_url = request.get_full_path()
        # La modale de création doit poster avec la catégorie résolue.
        if needs_type and instance is None and problem_type is not None:
            separator = "&" if "?" in save_url else "?"
            save_url = (
                save_url
                if "type=" in save_url
                else f"{save_url}{separator}type={problem_type.pk}"
            )
        return render_modal(
            request, form=form, title=title, save_url=save_url
        )

    # --- POST --- #
    if spec.get("plain_form"):  # RequiredCourse : formulaire simple
        if not form.is_valid():
            return form_error_json(form)
        if ProblemTypeRequiredCourse.objects.filter(
            problem_type=problem_type, course=form.cleaned_data["course"]
        ).exists():
            return form_error_json(
                form, message=_("Ce cours est déjà requis pour cette catégorie.")
            )
        try:
            with transaction.atomic():
                link = ProblemTypeRequiredCourse.objects.create(
                    problem_type=problem_type,
                    course=form.cleaned_data["course"],
                    is_required=form.cleaned_data.get("is_required", True),
                )
        except IntegrityError:
            return form_error_json(form, message=_("Conflit de données (doublon ?)."))
        audit_service.record(
            request,
            audit_service.AuditLog.Action.CREATE,
            obj=link,
            university=university,
        )
        return json_ok(_("Cours requis ajouté."))

    if instance is None and kind in ("field", "attachment", "rule", "decision"):
        form.instance.problem_type = problem_type  # propriété serveur

    return save_model_form(
        request,
        form,
        message=_("%(label)s enregistré(e).") % {"label": spec["label"]},
        university=university,
    )


@require_POST
@console_required(*PERMS)
def admin_workflow_toggle(request, kind: str):
    """Active/désactive une configuration (désactivation douce)."""
    spec = TYPE_KINDS.get(kind)
    if spec is None or kind not in TOGGLE_KINDS:
        return json_error(_("Type de configuration inconnu."), status=404)
    university = resolve_university(request)
    pk = parse_uuid(request.POST.get("pk"))
    if pk is None:
        return json_error(_("Paramètre « pk » manquant."))
    obj = spec["model"]._default_manager.filter(pk=pk).first()
    if obj is None:
        return json_error(_("Objet introuvable."), status=404)
    if kind in ("field", "decision"):
        if not _in_type_scope(obj, university):
            return json_error(_("Objet hors périmètre."), status=403)
    elif not _in_university_scope(spec, obj, university):
        return json_error(_("Objet hors périmètre."), status=403)

    previous = bool(obj.is_active)
    with transaction.atomic():
        obj.is_active = not previous
        obj.save(update_fields=["is_active"])
    audit_service.record(
        request,
        audit_service.AuditLog.Action.UPDATE,
        obj=obj,
        changes={"is_active": {"from": previous, "to": not previous}},
        university=university,
    )
    state = _("activé") if not previous else _("désactivé")
    return json_ok(_("%(label)s : %(state)s.") % {"label": spec["label"], "state": state})


@require_POST
@console_required(*PERMS)
def admin_workflow_delete(request, kind: str):
    """Suppression d'une configuration (jamais d'entité porteuse d'historique)."""
    spec = TYPE_KINDS.get(kind)
    if spec is None or kind not in DELETE_KINDS:
        return json_error(_("Type de configuration inconnu."), status=404)
    university = resolve_university(request)
    pk = parse_uuid(request.POST.get("pk"))
    if pk is None:
        return json_error(_("Paramètre « pk » manquant."))
    obj = spec["model"]._default_manager.filter(pk=pk).first()
    if obj is None:
        return json_error(_("Objet introuvable."), status=404)
    if not _in_type_scope(obj, university):
        return json_error(_("Objet hors périmètre."), status=403)

    label = str(obj)
    try:
        with transaction.atomic():
            obj.delete()
    except (ProtectedError, RestrictedError):
        return json_error(
            _("Impossible de supprimer : cet élément est encore utilisé."),
            status=400,
        )
    except IntegrityError:
        return json_error(_("Conflit de données : suppression impossible."), status=400)

    audit_service.record(
        request,
        audit_service.AuditLog.Action.DELETE,
        model_label=f"{spec['model']._meta.app_label}.{spec['model']._meta.model_name}",
        object_pk=str(pk),
        object_repr=label[:255],
        university=university,
    )
    return json_ok(_("%(label)s supprimé.") % {"label": spec["label"]})
