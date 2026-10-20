"""
Coque SPA — rendu unifié des vues-fragments.

Les vues de tableau de bord renvoient des fragments HTML injectés dans
`#spa-viewport`. Elles sont normalement appelées par `fetch()` (en-tête
`X-Requested-With`). Un accès direct — F5, lien partagé — doit renvoyer la
coque complète avec le fragment demandé : sans cela, le navigateur affiche
le fragment brut, sans `<head>` ni feuille de style.

`spa_page` détecte donc les navigations document et rend la coque
`dashboard/index.html` en **inlinant le HTML du fragment déjà produit** :
le contenu s'affiche immédiatement, sans second aller-retour fetch ni
double exécution de la vue. Si l'inlining échoue, le JS re-fetch le
fragment comme repli (`data-fragment-inlined`).
"""

from functools import wraps

from django.http import Http404
from django.shortcuts import render
from django.urls import resolve, reverse

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


def build_dashboard_context(
    request, initial_fragment=None, initial_fragment_html=None
):
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
        "initial_fragment_html": initial_fragment_html,
        "needs_onboarding": (
            role == ROLE_STUDENT
            and not request.user.student_profile.is_onboarded
        ),
        "onboarding_modal": reverse("accounts:onboarding_modal"),
    }


_XHR_HEADER = "HTTP_X_REQUESTED_WITH"


def _fragment_html(response):
    """HTML du fragment si la réponse est un fragment 200 exploitable."""
    if (
        response.status_code == 200
        and not getattr(response, "streaming", False)
        and "text/html" in response.get("Content-Type", "")
    ):
        return response.content.decode(response.charset, errors="replace")
    return None


def render_inline_fragment(request, url):
    """Rend la vue-fragment de `url` et renvoie son HTML (sinon None).

    Marque temporairement la requête comme XHR pour que `spa_page`
    renvoie le fragment nu. Toute erreur, redirection ou réponse
    non-HTML renvoie None : le chargement JS reste le repli.
    """
    path = str(url).split("?", 1)[0].split("#", 1)[0]
    if path.startswith(("http://", "https://")):
        return None
    try:
        match = resolve(path)
    except Http404:
        return None
    previous = request.META.get(_XHR_HEADER)
    request.META[_XHR_HEADER] = "XMLHttpRequest"
    try:
        response = match.func(request, *match.args, **match.kwargs)
    except Exception:  # noqa: BLE001 — repli JS silencieux
        return None
    finally:
        if previous is None:
            request.META.pop(_XHR_HEADER, None)
        else:
            request.META[_XHR_HEADER] = previous
    return _fragment_html(response)


def render_dashboard_shell(request, initial_fragment=None, fragment_html=None):
    """Coque + fragment initial inliné : un seul aller-retour réseau.

    `fragment_html` est fourni par `spa_page` (HTML déjà rendu par la
    vue) ; sinon la vue-fragment est exécutée ici en requête XHR simulée.
    """
    fragment_url = initial_fragment or reverse(
        role_dashboard_url(role_name(request.user))
    )
    if fragment_html is None:
        fragment_html = render_inline_fragment(request, fragment_url)
    return render(
        request,
        "dashboard/index.html",
        build_dashboard_context(
            request,
            initial_fragment=fragment_url,
            initial_fragment_html=fragment_html,
        ),
    )


def spa_page(view):
    """
    Rend la coque complète pour un accès direct à une vue-fragment.

    Le HTML du fragment — déjà produit par la vue — est inliné dans la
    coque : ni second rendu serveur, ni fetch initial côté client. Les
    requêtes AJAX (fetch) et non-GET passent inchangées ; les erreurs
    (JSON 401/403, redirections) également.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != "GET" or is_fragment_request(request):
            return view(request, *args, **kwargs)

        response = view(request, *args, **kwargs)
        fragment_html = _fragment_html(response)
        if fragment_html is not None and role_name(request.user) is not None:
            return render_dashboard_shell(
                request,
                initial_fragment=request.get_full_path(),
                fragment_html=fragment_html,
            )
        return response

    return wrapper
