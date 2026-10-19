"""
Décorateurs d'autorisation — accounts.

Toutes les vues AJAX du projet sont accédées par `fetch()` : un échec de droits
doit donc renvoyer du **JSON** (401 non authentifié / 403 mauvais rôle), jamais une
redirection HTML. Les décorateurs attachent aussi le profil résolu à la requête
(`request.student` / `request.teacher`), évitant de le re-résoudre dans la vue —
et rappelant qu'on ne lit **jamais** un identifiant de profil côté client (§9.1).
"""

from functools import wraps

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _


def _json_error(message, status):
    return JsonResponse({"status": "error", "message": str(message)}, status=status)


def _resolve_profile(user, related_name):
    """Retourne le profil lié ou None (sans lever d'exception OneToOne)."""
    try:
        return getattr(user, related_name)
    except AttributeError:
        return None


def _profile_required(related_name, request_attr):
    """Fabrique un décorateur exigeant le profil OneToOne donné."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _json_error(_("Authentication required."), 401)
            profile = _resolve_profile(request.user, related_name)
            if profile is None:
                return _json_error(_("This account has no matching profile."), 403)
            setattr(request, request_attr, profile)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


# Étudiant : `request.user.student_profile`
student_required = _profile_required("student_profile", "student")
# Enseignant : `request.user.teacher_profile`
teacher_required = _profile_required("teacher_profile", "teacher")


def superuser_required(view):
    """Réservé aux super-administrateurs (console d'import, analytique)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _json_error(_("Authentication required."), 401)
        if not request.user.is_superuser:
            return _json_error(_("Super administrator rights required."), 403)
        return view(request, *args, **kwargs)

    return wrapper


def console_required(*perms):
    """
    Accès à un module de la console super-admin (C1–C6).

    * super-administrateur → accès total ;
    * sinon → il faut posséder **au moins une** des permissions Django
      listées (module = frontière de capacité, attribuable depuis
      « Comptes → Permissions »).

    Les actions sensibles (émission d'accès, révocation de sessions,
    retrait des droits d'administrateur) restent sous `superuser_required`.
    Les échecs renvoient du JSON : toutes les vues de la console sont
    consommées par `fetch()` (cf. docstring du module).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _json_error(_("Authentication required."), 401)
            if request.user.is_superuser:
                return view(request, *args, **kwargs)
            if perms and any(request.user.has_perm(perm) for perm in perms):
                return view(request, *args, **kwargs)
            return _json_error(
                _("Insufficient permissions for this console module."), 403
            )

        return wrapper

    return decorator


def superuser_page_required(view):
    """
    Variante HTML de `superuser_required` pour les pages de la console :
    anonyme → redirection vers la landing ; mauvais rôle → 403 explicite.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:landing")
        if not request.user.is_superuser:
            return render(request, "errors/403.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def login_required_json(view):
    """Exige une session authentifiée, réponse JSON sinon."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _json_error(_("Authentication required."), 401)
        return view(request, *args, **kwargs)

    return wrapper
