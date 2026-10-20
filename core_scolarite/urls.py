"""
Routage de l'app core_scolarite — namespace « core_scolarite ».

  GET  /scolarite/ajax/form-config/       configuration dynamique du formulaire
  GET  /scolarite/ajax/problem-types/     liste des types de problème
  GET  /scolarite/admin/import/           modale d'import (superuser)
  POST /scolarite/admin/import/preview/   aperçu ETL + rapport ligne à ligne
  POST /scolarite/admin/import/commit/    confirmation d'écriture (jeton signé)
  GET  /scolarite/admin/import/template/  modèle CSV/XLSX des en-têtes requis
  POST /scolarite/admin/import/upload/    import direct (API historique)
  GET  /scolarite/admin/accounts/new/     modale de création manuelle (superuser)
  POST /scolarite/admin/accounts/create/  création manuelle (superuser)
  GET  /scolarite/admin/analytics/        tableau de bord analytique (C0)

  C1  /scolarite/admin/users/…            comptes (liste, modale, bascule, accès)
  C2  /scolarite/admin/structure/…        organisation (onglets, modales, bascules)
  C3  /scolarite/admin/requests/…         suivi central (consultation seule)
  C4  /scolarite/admin/workflow/…         configuration (types, champs, règles…)
  C5  /scolarite/admin/reports/…          statistiques + exports CSV/PDF
  C6  /scolarite/admin/security/…         audit, incidents, sessions
"""

from django.urls import path

from .views import (
    admin_actions,
    admin_organization,
    admin_reports,
    admin_requests,
    admin_security,
    admin_users,
    admin_workflow,
    ajax_selectors,
    analytics,
    base,
)

app_name = "core_scolarite"

urlpatterns = [
    path("ajax/form-config/", ajax_selectors.form_config, name="form_config"),
    path("ajax/problem-types/", ajax_selectors.problem_types, name="problem_types"),
    path("admin/import/", base.admin_import_modal, name="admin_import_modal"),
    path(
        "admin/import/upload/",
        admin_actions.admin_import_upload,
        name="admin_import_upload",
    ),
    path(
        "admin/import/preview/",
        admin_actions.admin_import_preview,
        name="admin_import_preview",
    ),
    path(
        "admin/import/commit/",
        admin_actions.admin_import_commit,
        name="admin_import_commit",
    ),
    path(
        "admin/import/template/",
        admin_actions.admin_import_template,
        name="admin_import_template",
    ),
    path(
        "admin/accounts/new/",
        base.admin_manual_account_modal,
        name="admin_manual_account_modal",
    ),
    path(
        "admin/accounts/create/",
        admin_actions.admin_create_account,
        name="admin_create_account",
    ),
    path("admin/analytics/", analytics.admin_analytics, name="admin_analytics"),
    # --- C1 : utilisateurs -------------------------------------------------- #
    path("admin/users/", admin_users.admin_users, name="admin_users"),
    path("admin/users/modal/", admin_users.admin_users_modal, name="admin_users_modal"),
    path(
        "admin/users/toggle/", admin_users.admin_users_toggle, name="admin_users_toggle"
    ),
    path(
        "admin/users/credentials/",
        admin_users.admin_users_credentials,
        name="admin_users_credentials",
    ),
    # --- C2 : organisation --------------------------------------------------- #
    path(
        "admin/structure/",
        admin_organization.admin_organization,
        name="admin_organization",
    ),
    path(
        "admin/structure/modal/<str:kind>/",
        admin_organization.admin_organization_modal,
        name="admin_organization_modal",
    ),
    path(
        "admin/structure/toggle/<str:kind>/",
        admin_organization.admin_organization_toggle,
        name="admin_organization_toggle",
    ),
    # --- C3 : requêtes ------------------------------------------------------- #
    path("admin/requests/", admin_requests.admin_requests, name="admin_requests"),
    path(
        "admin/requests/list/",
        admin_requests.admin_requests_list,
        name="admin_requests_list",
    ),
    path(
        "admin/requests/detail/",
        admin_requests.admin_requests_detail,
        name="admin_requests_detail",
    ),
    # --- C4 : workflow ------------------------------------------------------- #
    path("admin/workflow/", admin_workflow.admin_workflow, name="admin_workflow"),
    path(
        "admin/workflow/modal/<str:kind>/",
        admin_workflow.admin_workflow_modal,
        name="admin_workflow_modal",
    ),
    path(
        "admin/workflow/toggle/<str:kind>/",
        admin_workflow.admin_workflow_toggle,
        name="admin_workflow_toggle",
    ),
    path(
        "admin/workflow/delete/<str:kind>/",
        admin_workflow.admin_workflow_delete,
        name="admin_workflow_delete",
    ),
    # --- C5 : rapports ------------------------------------------------------- #
    path("admin/reports/", admin_reports.admin_reports, name="admin_reports"),
    path("admin/reports/csv/", admin_reports.admin_reports_csv, name="admin_reports_csv"),
    path("admin/reports/pdf/", admin_reports.admin_reports_pdf, name="admin_reports_pdf"),
    # --- C6 : sécurité & audit ---------------------------------------------- #
    path("admin/security/", admin_security.admin_security, name="admin_security"),
    path(
        "admin/security/incident/modal/",
        admin_security.admin_security_incident_modal,
        name="admin_security_incident_modal",
    ),
    path(
        "admin/security/event/resolve/",
        admin_security.admin_security_event_resolve,
        name="admin_security_event_resolve",
    ),
    path(
        "admin/security/session/revoke/",
        admin_security.admin_security_session_revoke,
        name="admin_security_session_revoke",
    ),
]
