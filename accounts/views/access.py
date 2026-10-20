"""
Première connexion & mot de passe oublié — vues publiques (accounts).

Parcours (brief UnivReq §3) :
  GET/POST /activation/                 matricule + e-mail → lien à usage unique
  GET/POST /activation/<token>/         définition du mot de passe + activation
  GET/POST /mot-de-passe-oublie/        matricule (ou e-mail) + e-mail → lien
  GET/POST /reinitialisation/<token>/   nouveau mot de passe

Garanties serveur :
  * aucun compte n'est révélé (message identique, que le matricule existe ou
    non, et que l'e-mail corresponde ou non) ;
  * vérification stricte de la correspondance matricule ↔ e-mail du compte ;
  * jeton à usage unique, expiré, comparé par empreinte (jamais en clair) ;
  * limitation des tentatives (cache, 5 demandes / heure par identifiant) ;
  * validation Django des mots de passe, aucune conservation en clair ;
  * journalisation des opérations sensibles (audit).
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from accounts.models import AccessLink
from accounts.services import access_links

User = get_user_model()
logger = logging.getLogger(__name__)

RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 3600


def _audit(user, action: str, changes: dict | None = None, request=None) -> None:
    """Journalise une opération sensible (best-effort, jamais bloquant)."""
    try:
        from core_scolarite.services import audit as audit_service

        if request is not None:
            audit_service.record(
                request, action, obj=user, changes=changes or {},
                model_label="accounts.AccessLink",
            )
        else:
            from core_scolarite.models import AuditLog

            AuditLog.record(action=action, obj=user, changes=changes or {})
    except Exception:  # noqa: BLE001 — l'audit ne doit jamais faire échouer le parcours
        pass


# --------------------------------------------------------------------------- #
# Limitation des tentatives (anti-force brute sur matricule + e-mail)
# --------------------------------------------------------------------------- #

def _rate_key(request, identifier: str) -> str:
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    ip = ip or request.META.get("REMOTE_ADDR") or "unknown"
    return f"access-link:{ip}:{identifier.strip().lower()}"


def _throttled(request, identifier: str) -> bool:
    return (cache.get(_rate_key(request, identifier)) or 0) >= RATE_LIMIT


def _register_request(request, identifier: str) -> None:
    key = _rate_key(request, identifier)
    cache.set(key, (cache.get(key) or 0) + 1, RATE_WINDOW_SECONDS)


def _lookup_user(matricule: str, email: str):
    """Compte dont le matricule ET l'e-mail correspondent (comparaison insensible)."""
    if not matricule or not email:
        return None
    return (
        User.objects.filter(username__iexact=matricule.strip())
        .filter(email__iexact=email.strip())
        .first()
    )


def _send_or_log(user, raw_token: str, purpose: str, request=None) -> None:
    """
    Envoie le lien par e-mail ; un échec SMTP est journalisé (alerte serveur)
    mais ne casse jamais le parcours ni ne divulgue l'existence du compte.
    L'administrateur dispose en parallèle de la procédure contrôlée
    « Générer un lien de première connexion » (console C1).
    """
    try:
        access_links.send_link_email(user, raw_token, purpose, request=request)
    except Exception:  # noqa: BLE001 — SMTP indisponible : journalisé, pas exposé
        logger.exception(
            "Échec d'envoi du lien d'accès (%s) pour le matricule %s",
            purpose,
            user.username,
        )


def _render(request, template: str, context: dict, status: int = 200):
    return render(request, template, context, status=status)


# --------------------------------------------------------------------------- #
# 1. Demande de lien (première connexion)
# --------------------------------------------------------------------------- #

@require_http_methods(["GET", "POST"])
def activation_request(request):
    """Saisie matricule + e-mail → envoi du lien de première connexion."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    context = {
        "page_title": _("Première connexion"),
        "intro": _(
            "Saisissez votre matricule et l'adresse e-mail enregistrée : un "
            "lien temporaire et à usage unique vous sera envoyé pour définir "
            "votre mot de passe et activer votre compte."
        ),
        "submit_label": _("Envoyer le lien d'activation"),
        "alternate_url": reverse("accounts:reset_request"),
        "alternate_label": _("Mot de passe oublié ?"),
    }

    if request.method == "GET":
        return _render(request, "access/request.html", context)

    matricule = request.POST.get("matricule") or ""
    email = request.POST.get("email") or ""

    if not matricule.strip() or not email.strip():
        context["form_error"] = _("Le matricule et l'adresse e-mail sont requis.")
        return _render(request, "access/request.html", context, status=400)

    if _throttled(request, matricule):
        context["form_error"] = _(
            "Trop de demandes effectuées. Patientez avant de réessayer."
        )
        return _render(request, "access/request.html", context, status=429)

    _register_request(request, matricule)

    user = _lookup_user(matricule, email)
    # Compte étudiant ou enseignant uniquement (jamais un compte administrateur).
    if user is not None and (
        getattr(user, "student_profile", None) is None
        and getattr(user, "teacher_profile", None) is None
    ):
        user = None

    if user is not None:
        issued_link, raw_token = access_links.issue_link(
            user, AccessLink.Purpose.ACTIVATION, email=email.strip()
        )
        del issued_link  # le lien n'existe que sous forme de jeton envoyé
        _send_or_log(user, raw_token, AccessLink.Purpose.ACTIVATION, request=request)
        _audit(user, "credentials", {"link": "activation", "channel": "email"})

    # Message identique dans tous les cas : aucune divulgation de compte.
    context["sent"] = True
    context["success_message"] = _(
        "Si le matricule et l'adresse e-mail correspondent à un compte, un "
        "lien de première connexion vient d'être envoyé. Consultez votre "
        "boîte mail (et vos spams)."
    )
    return _render(request, "access/request.html", context)


# --------------------------------------------------------------------------- #
# 2. Activation : définition du mot de passe
# --------------------------------------------------------------------------- #

@require_http_methods(["GET", "POST"])
def activation_confirm(request, token: str):
    """Lien de première connexion → choix du mot de passe, activation du compte."""
    link = access_links.resolve(token, AccessLink.Purpose.ACTIVATION)
    if link is None:
        return _render(
            request,
            "access/set_password.html",
            {
                "page_title": _("Première connexion"),
                "link_error": _(
                    "Ce lien est expiré, déjà utilisé ou invalide. Relancez une "
                    "demande depuis la page de connexion."
                ),
                "request_url": reverse("accounts:activation_request"),
            },
            status=400,
        )

    context = {
        "page_title": _("Définir mon mot de passe"),
        "intro": _(
            "Choisissez le mot de passe de votre compte %(matricule)s. Il "
            "remplace définitivement l'accès transmis par l'administration."
        )
        % {"matricule": link.user.username},
        "form_action": reverse("accounts:activation_confirm", args=[token]),
        "matricule": link.user.username,
    }

    if request.method == "GET":
        return _render(request, "access/set_password.html", context)

    error = _apply_new_password(link.user, request)
    if error:
        context["form_error"] = error
        return _render(request, "access/set_password.html", context, status=400)

    with transaction.atomic():
        access_links.consume(link)
        # L'activation débloque le compte créé par l'administration.
        if not link.user.is_active:
            link.user.is_active = True
            link.user.save(update_fields=["is_active"])
    _audit(link.user, "credentials", {"link": "activation", "result": "activated"})

    context["done"] = True
    context["success_message"] = _(
        "Votre compte est activé. Connectez-vous avec votre matricule (ou "
        "votre e-mail) et votre nouveau mot de passe."
    )
    context["login_url"] = reverse("accounts:login_page")
    return _render(request, "access/set_password.html", context)


# --------------------------------------------------------------------------- #
# 3. Mot de passe oublié
# --------------------------------------------------------------------------- #

@require_http_methods(["GET", "POST"])
def reset_request(request):
    """Saisie matricule (ou e-mail) + e-mail → lien de réinitialisation."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    context = {
        "page_title": _("Mot de passe oublié"),
        "intro": _(
            "Saisissez votre matricule et l'adresse e-mail enregistrée : un "
            "lien temporaire et à usage unique vous sera envoyé pour choisir "
            "un nouveau mot de passe."
        ),
        "submit_label": _("Envoyer le lien de réinitialisation"),
        "alternate_url": reverse("accounts:activation_request"),
        "alternate_label": _("Première connexion ?"),
    }

    if request.method == "GET":
        return _render(request, "access/request.html", context)

    matricule = request.POST.get("matricule") or ""
    email = request.POST.get("email") or ""

    if not matricule.strip() or not email.strip():
        context["form_error"] = _("Le matricule et l'adresse e-mail sont requis.")
        return _render(request, "access/request.html", context, status=400)

    if _throttled(request, matricule):
        context["form_error"] = _(
            "Trop de demandes effectuées. Patientez avant de réessayer."
        )
        return _render(request, "access/request.html", context, status=429)

    _register_request(request, matricule)

    user = _lookup_user(matricule, email)
    if user is not None:
        issued_link, raw_token = access_links.issue_link(
            user, AccessLink.Purpose.RESET, email=email.strip()
        )
        del issued_link  # le lien n'existe que sous forme de jeton envoyé
        _send_or_log(user, raw_token, AccessLink.Purpose.RESET, request=request)
        _audit(user, "credentials", {"link": "password_reset", "channel": "email"})

    context["sent"] = True
    context["success_message"] = _(
        "Si le matricule et l'adresse e-mail correspondent à un compte, un "
        "lien de réinitialisation vient d'être envoyé. Consultez votre boîte "
        "mail (et vos spams)."
    )
    return _render(request, "access/request.html", context)


@require_http_methods(["GET", "POST"])
def password_reset_confirm(request, token: str):
    """Lien de réinitialisation → nouveau mot de passe."""
    link = access_links.resolve(token, AccessLink.Purpose.RESET)
    if link is None:
        return _render(
            request,
            "access/set_password.html",
            {
                "page_title": _("Mot de passe oublié"),
                "link_error": _(
                    "Ce lien est expiré, déjà utilisé ou invalide. Relancez une "
                    "demande depuis la page de connexion."
                ),
                "request_url": reverse("accounts:reset_request"),
            },
            status=400,
        )

    context = {
        "page_title": _("Nouveau mot de passe"),
        "intro": _(
            "Choisissez le nouveau mot de passe du compte %(matricule)s."
        )
        % {"matricule": link.user.username},
        "form_action": reverse("accounts:password_reset_confirm", args=[token]),
        "matricule": link.user.username,
    }

    if request.method == "GET":
        return _render(request, "access/set_password.html", context)

    error = _apply_new_password(link.user, request)
    if error:
        context["form_error"] = error
        return _render(request, "access/set_password.html", context, status=400)

    access_links.consume(link)
    _audit(link.user, "credentials", {"link": "password_reset", "result": "reset"})

    context["done"] = True
    context["success_message"] = _(
        "Votre mot de passe a été modifié. Connectez-vous avec votre matricule "
        "(ou votre e-mail) et ce nouveau mot de passe."
    )
    context["login_url"] = reverse("accounts:login_page")
    return _render(request, "access/set_password.html", context)


# --------------------------------------------------------------------------- #
# Validation commune du nouveau mot de passe
# --------------------------------------------------------------------------- #

def _apply_new_password(user, request) -> str | None:
    """Valide puis applique le mot de passe choisi. Renvoie le message d'erreur."""
    password1 = request.POST.get("password1") or ""
    password2 = request.POST.get("password2") or ""

    if not password1 or not password2:
        return _("Veuillez saisir le mot de passe et sa confirmation.")
    if password1 != password2:
        return _("Les deux mots de passe ne correspondent pas.")
    try:
        validate_password(password1, user=user)
    except DjangoValidationError as exc:
        return " ".join(exc.messages)

    user.set_password(password1)
    user.save(update_fields=["password"])
    return None
