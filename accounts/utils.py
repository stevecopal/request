"""
Utilitaires accounts — détection de rôle et définition de la navigation.

`role_name()` centralise « quel rôle pour cet utilisateur ? » (routage du
dashboard, actions AJAX, templates).

`nav_sections(role)` définit **une seule fois** la navigation, regroupée en
sections pour la barre latérale ; `nav_items(role)` en fournit la version
aplatie, consommée par la navigation basse mobile. Les URLs sont toujours
construites via `reverse` (aucune duplication).
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

ROLE_ADMIN = "admin"
ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"

_ROLE_LABELS = {
    ROLE_STUDENT: _("Étudiant"),
    ROLE_TEACHER: _("Enseignant"),
    ROLE_ADMIN: _("Super-administrateur"),
}

# Marqueurs SVG internes (stroke, 24x24) — réutilisables dans toutes les navs.
_ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
    "documents": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8M16 17H8M10 9H8"/>',
    "plus": '<circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "user-plus": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>',
    "home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    # --- Console super-admin (modules C1–C6) ---
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "building": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 7h1.5M13.5 7H15M9 11h1.5M13.5 11H15M9 15h1.5M13.5 15H15"/><path d="M10 21v-3h4v3"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2z"/>',
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


def role_label(role):
    """Libellé humain du rôle (barre latérale, en-tête, profil)."""
    return _ROLE_LABELS.get(role, _("Utilisateur"))


def role_dashboard_url(role):
    """Fragment initial du dashboard selon le rôle (clé d'URL reverse)."""
    return {
        ROLE_STUDENT: "tickets:student_home",
        ROLE_TEACHER: "tickets:teacher_home",
        ROLE_ADMIN: "core_scolarite:admin_analytics",
    }.get(role)


def _item(label, url, icon, *, description="", is_modal=False,
          modal_title=None, badge=None):
    return {
        "label": label,
        "url": url,
        "icon": _ICONS[icon],
        "description": description,
        "is_modal": is_modal,
        "modal_title": modal_title or label,
        "aria_current": False,
        "badge": badge,
    }


def nav_sections(role, unread_notifications=0):
    """
    Navigation du rôle regroupée en sections (barre latérale).

    Renvoie une liste de ``{"label": str, "items": [item, …]}``. Les entrées
    ``is_modal=True`` ouvrent la modale maîtresse (``data-modal-src``) ; les
    autres chargent un fragment dans ``#spa-viewport`` (``data-fragment-src``).

    La console super-admin est découpée selon les modules fonctionnels
    (C1 utilisateurs, C2 organisation, C3 requêtes, C4 configuration,
    C5 statistiques, C6 sécurité/audit).
    """
    sections: list[dict] = []

    if role == ROLE_STUDENT:
        sections.append(
            {
                "label": _("Principal"),
                "items": [
                    _item(
                        _("Tableau de bord"),
                        reverse("tickets:student_home"),
                        "dashboard",
                        description=_("Vue d'ensemble de vos requêtes"),
                    ),
                    _item(
                        _("Mes requêtes"),
                        reverse("tickets:student_feed"),
                        "documents",
                        description=_("Suivre et filtrer vos demandes"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Actions"),
                "items": [
                    _item(
                        _("Nouvelle requête"),
                        reverse("tickets:student_request_modal"),
                        "plus",
                        description=_("Soumettre une nouvelle demande"),
                        is_modal=True,
                        modal_title=_("Nouvelle requête"),
                    ),
                ],
            }
        )
    elif role == ROLE_TEACHER:
        sections.append(
            {
                "label": _("Principal"),
                "items": [
                    _item(
                        _("Tableau de bord"),
                        reverse("tickets:teacher_home"),
                        "dashboard",
                        description=_("Vue d'ensemble des requêtes"),
                    ),
                    _item(
                        _("À traiter"),
                        reverse("tickets:teacher_inbox"),
                        "inbox",
                        description=_("Traiter les requêtes assignées"),
                    ),
                ],
            }
        )
    elif role == ROLE_ADMIN:
        sections.append(
            {
                "label": _("Pilotage"),
                "items": [
                    _item(
                        _("Tableau de bord"),
                        reverse("core_scolarite:admin_analytics"),
                        "chart",
                        description=_("Indicateurs de la plateforme"),
                    ),
                    _item(
                        _("Statistiques & rapports"),
                        reverse("core_scolarite:admin_reports"),
                        "documents",
                        description=_("Volumes, délais, export CSV"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Utilisateurs"),
                "items": [
                    _item(
                        _("Comptes"),
                        reverse("core_scolarite:admin_users"),
                        "users",
                        description=_("Étudiants et enseignants"),
                    ),
                    _item(
                        _("Nouveau compte"),
                        reverse("core_scolarite:admin_manual_account_modal"),
                        "user-plus",
                        description=_("Créer un compte manuellement"),
                        is_modal=True,
                        modal_title=_("Nouveau compte"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Organisation"),
                "items": [
                    _item(
                        _("Structure académique"),
                        reverse("core_scolarite:admin_organization"),
                        "building",
                        description=_("Facultés, départements, filières"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Requêtes"),
                "items": [
                    _item(
                        _("Toutes les requêtes"),
                        reverse("core_scolarite:admin_requests"),
                        "inbox",
                        description=_("Suivi central : statut et temps de traitement"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Configuration"),
                "items": [
                    _item(
                        _("Workflow & formulaires"),
                        reverse("core_scolarite:admin_workflow"),
                        "sliders",
                        description=_("Types, champs, délais, relances"),
                    ),
                ],
            }
        )
        sections.append(
            {
                "label": _("Système"),
                "items": [
                    _item(
                        _("Sécurité & audit"),
                        reverse("core_scolarite:admin_security"),
                        "shield",
                        description=_("Journal, accès, synchronisation"),
                    ),
                    _item(
                        _("Importer"),
                        reverse("core_scolarite:admin_import_modal"),
                        "upload",
                        description=_("Charger des données (CSV/Excel)"),
                        is_modal=True,
                        modal_title=_("Import de données"),
                    ),
                ],
            }
        )

    # Section « Compte » commune (notifications pour étudiant/enseignant, profil).
    account = []
    if role in (ROLE_STUDENT, ROLE_TEACHER):
        account.append(
            _item(
                _("Notifications"),
                reverse("accounts:notifications"),
                "bell",
                description=_("Vos alertes et messages"),
                badge=unread_notifications,
            )
        )
    account.append(
        _item(
            _("Profil"),
            reverse("accounts:profile"),
            "user",
            description=_("Vos informations de compte"),
        )
    )
    sections.append({"label": _("Compte"), "items": account})

    sections = [section for section in sections if section["items"]]

    # Premier item de la première section = page d'accueil du rôle.
    if sections and sections[0]["items"]:
        sections[0]["items"][0]["aria_current"] = True
    return sections


def nav_items(role, unread_notifications=0):
    """
    Version aplatie de `nav_sections` — consommée par la navigation basse
    mobile et les tests historiques. Conserve la forme de dictionnaire
    `{label, url, icon, is_modal, modal_title, aria_current, badge, …}`.
    """
    flat = []
    for section in nav_sections(role, unread_notifications=unread_notifications):
        flat.extend(section["items"])
    return flat
