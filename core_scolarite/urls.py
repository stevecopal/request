"""
Routage de l'app core_scolarite — namespace « core_scolarite ».

  GET  /scolarite/ajax/form-config/       configuration dynamique du formulaire
  GET  /scolarite/ajax/problem-types/     liste des types de problème
  GET  /scolarite/admin/import/           modale d'import (superuser)
  POST /scolarite/admin/import/upload/    upload ETL (superuser)
  GET  /scolarite/admin/accounts/new/     modale de création manuelle (superuser)
  POST /scolarite/admin/accounts/create/  création manuelle (superuser)
  GET  /scolarite/admin/analytics/        tableau de bord analytique (superuser)
"""

from django.urls import path

from .views import admin_actions, ajax_selectors, analytics, base

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
]
