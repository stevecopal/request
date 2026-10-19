"""
Coque SPA — rendu unifié des vues-fragments.

Les vues de tableau de bord renvoient des fragments HTML injectés dans
`#spa-viewport`. Elles sont normalement appelées par `fetch()` (en-tête
`X-Requested-With`). Un accès direct — F5, lien partagé — doit renvoyer la
coque complète avec le fragment demandé : sans cela, le navigateur affiche
le fragment brut, sans `<head>` ni feuille de style.

`spa_page` détecte donc les navigations document et re-rend la coque
`dashboard/index.html` en conservant l'URL courante (filtres compris) comme
fragment initial.
"""

from functools import wraps

from django.shortcuts import render
from django.urls import reverse

from accounts.utils import (
    ROLE_STUDENT,
    nav_items,
    nav_sections,
    role_dashboard_url,
    role_label,
    role_name,
)


def is_fragment_request(request):
    """Vrai lorsque l'appel provient du chargeur de fragments (fetch)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def build_dashboard_context(request, initial_fragment=None):
    """Contexte commun de la coque : navigation, rôle, fragment initial."""
    role = role_name(request.user)
    unread_notifications = 0
    if role in (ROLE_STUDENT, "teacher"):
        from accounts.models import Notification

        unread_notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()

    return {
        "role": role,
        "role_label": role_label(role),
        "display_name": request.user.get_full_name() or request.user.username,
        "initials": (
            request.user.first_name[:1] + request.user.last_name[:1]
        ).upper()
        or request.user.username[:2].upper(),
        "nav_items": nav_items(role, unread_notifications=unread_notifications),
        "nav_sections": nav_sections(
            role, unread_notifications=unread_notifications
        ),
        "unread_notifications": unread_notifications,
        "initial_fragment": initial_fragment
        or reverse(role_dashboard_url(role)),
        "needs_onboarding": (
            role == ROLE_STUDENT
            and not request.user.student_profile.is_onboarded
        ),
        "onboarding_modal": reverse("accounts:onboarding_modal"),
    }


def spa_page(view):
    """
    Rend la coque complète pour un accès direct à une vue-fragment.

    Les requêtes AJAX (fetch) et non-GET passent inchangées ; les erreurs
    (JSON 401/403, redirections) également.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != "GET" or is_fragment_request(request):
            return view(request, *args, **kwargs)

        response = view(request, *args, **kwargs)
        content_type = response.get("Content-Type", "")
        if (
            response.status_code == 200
            and "text/html" in content_type
            and role_name(request.user) is not None
        ):
            return render(
                request,
                "dashboard/index.html",
                build_dashboard_context(
                    request, initial_fragment=request.get_full_path()
                ),
            )
        return response

    return wrapper
