"""
Helpers partagés des vues de console (C1–C6).

Conventions de la console :
  * **lecture** → fragment HTML (injecté dans `#spa-viewport` ou `#modal-body`) ;
  * **écriture** → `POST` répondant du JSON `{status, message, errors?}` —
    jamais de redirection (cf. docstring `accounts/decorators.py`) ;
  * **périmètre** : `resolve_university` + `in_scope` — aucun identifiant reçu
    côté client n'est cru sans contrôle objet ;
  * **traçabilité** : chaque écriture passe par `services.audit.record`.
"""

from __future__ import annotations

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError, models, transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from core_scolarite.services import audit as audit_service
from core_scolarite.services.audit import diff_changes
from core_scolarite.services.scoping import in_scope, parse_uuid

MODAL_TEMPLATE = "partials/admin/modal_form.html"

__all__ = [
    "json_error",
    "json_ok",
    "form_error_json",
    "save_model_form",
    "toggle_is_active",
    "scoped_object",
    "render_modal",
    "paginate",
]


def json_error(message, status: int = 400, **extra) -> JsonResponse:
    payload = {"status": "error", "message": str(message)}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def json_ok(message=None, **extra) -> JsonResponse:
    payload = {"status": "success"}
    if message:
        payload["message"] = str(message)
    payload.update(extra)
    return JsonResponse(payload)


def form_error_json(form, message=None, status: int = 400) -> JsonResponse:
    errors = [
        {"field": field, "message": " ".join(messages)}
        for field, messages in form.errors.items()
    ]
    return json_error(
        message or _("Formulaire invalide."), status=status, errors=errors
    )


def save_model_form(
    request,
    form,
    *,
    message: str,
    university=None,
    scope: str | None = None,
    success_status: str = "success",
):
    """
    Valide + enregistre un `ModelForm` de console, journalise l'écriture et
    renvoie la réponse JSON normalisée. Le diff calculé est celui **avant**
    mutation (colonnes réellement modifiées uniquement).
    """
    if not form.is_valid():
        return form_error_json(form)

    instance = form.instance
    created = instance.pk is None
    changes = {} if created else diff_changes(instance, dict(form.cleaned_data))

    try:
        with transaction.atomic():
            saved = form.save()
    except IntegrityError:
        return form_error_json(form, message=_("Conflit de données (doublon ?)."))

    if scope is not None and not in_scope(
        type(saved)._default_manager, scope, university, saved
    ):
        return json_error(
            _("Cet objet appartient à une autre université."), status=403
        )

    action = (
        audit_service.AuditLog.Action.CREATE
        if created
        else audit_service.AuditLog.Action.UPDATE
    )
    audit_service.record(
        request, action, obj=saved, changes=changes, university=university
    )
    return json_ok(message, pk=str(saved.pk), **{"created": created})


def parse_pk(model, raw):
    """Clé primaire adaptée au modèle : UUID pour `UUIDModel`, entier pour User."""
    if isinstance(model._meta.pk, models.UUIDField):
        return parse_uuid(raw)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def toggle_is_active(request, *, model, scope, university, label: str):
    """Active/désactive (désactivation douce) un objet de console."""
    pk = parse_pk(model, request.POST.get("pk"))
    if pk is None:
        return json_error(_("Paramètre « pk » manquant."))
    obj = model._default_manager.filter(pk=pk).first()
    if obj is None:
        return json_error(_("Objet introuvable."), status=404)
    if not in_scope(model._default_manager.all(), scope, university, obj):
        return json_error(
            _("Cet objet appartient à une autre université."), status=403
        )

    previous = bool(getattr(obj, "is_active", True))
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
    return json_ok(_("%(label)s : %(state)s.") % {"label": label, "state": state})


def scoped_object(model, request, *, scope, university, param: str = "pk", required: bool = True):
    """Charge un objet contrôlé par le périmètre université (ou `None`)."""
    pk = parse_pk(model, request.GET.get(param) or request.POST.get(param))
    if pk is None:
        return None
    obj = model._default_manager.filter(pk=pk).first()
    if obj is None:
        return None
    if not in_scope(model._default_manager.all(), scope, university, obj):
        return None
    return obj


def render_modal(request, *, form, title: str, save_url: str, extra: dict | None = None):
    """Fragment de modale générique (un seul template pour tous les formulaires)."""
    context = {"form": form, "title": title, "save_url": save_url}
    if extra:
        context.update(extra)
    return render(request, MODAL_TEMPLATE, context)


def paginate(request, queryset, *, per_page: int = 25, param: str = "page"):
    """Pagination tolérante (page hors bornes → dernière page utile)."""
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(param) or request.POST.get(param) or 1
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages or 1)
