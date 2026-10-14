"""
Utilitaires accounts — détection de rôle et définition de la navigation.

`role_name()` centralise « quel rôle pour cet utilisateur ? » (routage du
dashboard, actions AJAX, templates).

`nav_items(role)` définit **une seule fois** la navigation : la bottom-navigation
mobile et la navigation horizontale du desktop consomment exactement les mêmes
items (aucune duplication, URLs centralisées via `reverse`).
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

ROLE_ADMIN = "admin"
ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"

# Marqueurs SVG internes (stroke, 24x24) — réutilisables dans les deux navs.
_ICONS = {
    "documents": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8M16 17H8M10 9H8"/>',
    "plus": '<circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
}

def role_name(user):
    """Retourne 'admin' | 'student' | 'teacher' | None (jamais d'exception)."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return ROLE_ADMIN
    if getattr(user, "student_profile", None) is not None:
        return ROLE_STUDENT
    if getattr(user, "teacher_profile", None) is not None:
        return ROLE_TEACHER
    return None


def role_dashboard_url(role):
    """Fragment initial du dashboard selon le rôle (clé d'URL reverse)."""
    return {
        ROLE_STUDENT: "tickets:student_home",
        ROLE_TEACHER: "tickets:teacher_inbox",
        ROLE_ADMIN: "core_scolarite:admin_analytics",
    }.get(role)


def _item(label, url, icon, *, is_modal=False, modal_title=None, badge=None):
    return {
        "label": label,
        "url": url,
        "icon": _ICONS[icon],
        "is_modal": is_modal,
        "modal_title": modal_title or label,
        "aria_current": False,
        "badge": badge,
    }


def nav_items(role, unread_notifications=0):
    """
    Navigation complète du rôle, items déjà centrés (reverse).

    Les entrées `is_modal=True` ouvrent la modale maîtresse (data-modal-src) ;
    les autres chargent un fragment dans #spa-viewport (data-fragment-src).
    Le premier item est marqué `aria_current` par défaut (page d'accueil du rôle).
    `unread_notifications` alimente le badge de l'entrée « Notifications ».
    """
    items = []

    if role == ROLE_STUDENT:
        items.append(
            _item(_("Accueil"), reverse("tickets:student_home"), "home")
        )
        items.append(
            _item(_("Mes requêtes"), reverse("tickets:student_feed"), "documents")
        )
        items.append(
            _item(
                _("Nouvelle"),
                reverse("tickets:student_request_modal"),
                "plus",
                is_modal=True,
                modal_title=_("Nouvelle requête"),
            )
        )
    elif role == ROLE_TEACHER:
        items.append(
            _item(_("À traiter"), reverse("tickets:teacher_inbox"), "inbox")
        )

    if role in (ROLE_STUDENT, ROLE_TEACHER):
        items.append(
            _item(
                _("Notifications"),
                reverse("accounts:notifications"),
                "bell",
                badge=unread_notifications,
            )
        )

    if role == ROLE_ADMIN:
        items.append(
            _item(_("Pilotage"), reverse("core_scolarite:admin_analytics"), "chart")
        )
        items.append(
            _item(
                _("Import"),
                reverse("core_scolarite:admin_import_modal"),
                "upload",
                is_modal=True,
                modal_title=_("Import de données"),
            )
        )

    items.append(_item(_("Profil"), reverse("accounts:profile"), "user"))

    if items:
        items[0]["aria_current"] = True
    return items
