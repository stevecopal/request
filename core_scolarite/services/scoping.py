"""
Contexte université de la console SuperAdmin (isolation multi-tenants).

Règle : toute donnée affichée **ou modifiée** depuis la console l'est dans le
cadre d'une université de travail (paramètre GET/POST → session → défaut).
La portée est décrite par un « scope » par entité :

  * `None`              → entité plateforme (universités, années académiques) ;
  * chemin `"faculty__university"` → filtrage direct ;
  * callable `(qs, university) -> qs` → portée composée (ex. modèles globaux
    acceptés en plus de ceux de l'université).

`in_scope()` permet de refuser, côté serveur, toute écriture sur un objet
appartenant à une autre université (contrôle objet, pas seulement queryset).
"""

from __future__ import annotations

import uuid as uuid_lib

from accounts.models import University

SESSION_KEY = "console_university_id"


def parse_uuid(raw) -> uuid_lib.UUID | None:
    """Parse tolérant d'un UUID (jamais d'exception levée vers la vue)."""
    if not raw:
        return None
    try:
        return uuid_lib.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def resolve_university(request, raw=None) -> University | None:
    """
    Université de travail de la session courante.

    Priorité : argument explicite (POST/paramètre de la vue) → paramètre de la
    requête → session → première université par nom. Aucune université du
    système n'est jamais « devinée » à partir d'un objet métier client.
    """
    candidate = (
        parse_uuid(raw)
        or parse_uuid(request.GET.get("university"))
        or parse_uuid(request.POST.get("university"))
        or parse_uuid(request.session.get(SESSION_KEY))
    )
    if candidate is not None:
        found = University.objects.filter(pk=candidate).first()
        if found is not None:
            if request.session.get(SESSION_KEY) != str(found.pk):
                request.session[SESSION_KEY] = str(found.pk)
            return found

    default = University.objects.order_by("name").first()
    if default is None:
        request.session.pop(SESSION_KEY, None)
        return None
    if request.session.get(SESSION_KEY) != str(default.pk):
        request.session[SESSION_KEY] = str(default.pk)
    return default


def scoped(queryset, scope, university):
    """Applique la portée université (scope = chemin, callable ou None)."""
    if university is None or scope is None:
        return queryset
    if callable(scope):
        return scope(queryset, university)
    return queryset.filter(**{scope: university})


def in_scope(queryset, scope, university, obj) -> bool:
    """True si l'objet appartient à l'université de travail (contrôle serveur)."""
    if university is None or scope is None or obj is None:
        return True
    try:
        return scoped(queryset, scope, university).filter(pk=obj.pk).exists()
    except (ValueError, TypeError):
        return False
