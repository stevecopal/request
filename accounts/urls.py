"""
Routage de l'app accounts — namespace « accounts » (monté à la racine).

Routes (ARCHITECTURE §7.1) :
  GET  /                        landing
  GET  /login/                  fragment de la modale de connexion
  GET  /dashboard/              coque SPA (fragment initial selon le rôle)
  POST /accounts/login/         authentification JSON
  POST /accounts/logout/        déconnexion JSON
  GET  /accounts/profile/       fragment profil
  GET  /accounts/notifications/ fragment « Notifications » (centre)
  POST /accounts/ajax/notifications/read/  marquer comme lu
  GET  /accounts/onboarding/    fragment de la modale d'onboarding
  GET  /accounts/ajax/departments/   cascade faculté → département
  POST /accounts/ajax/onboarding/    enregistrement du rattachement
  POST /accounts/ajax/push/subscribe/   abonnement Web Push (appareil courant)
  POST /accounts/ajax/push/unsubscribe/ désabonnement Web Push
"""

from django.urls import path

from .views import ajax_actions, base, notifications

app_name = "accounts"

urlpatterns = [
    path("", base.landing_page, name="landing"),
    path("login/", base.login_fragment, name="login_page"),
    path("dashboard/", base.dashboard_shell, name="dashboard"),
    path("accounts/login/", ajax_actions.login_view, name="login"),
    path("accounts/logout/", ajax_actions.logout_view, name="logout"),
    path("accounts/profile/", base.profile_fragment, name="profile"),
    path(
        "accounts/notifications/",
        notifications.notifications_fragment,
        name="notifications",
    ),
    path(
        "accounts/ajax/notifications/read/",
        notifications.notifications_read,
        name="notifications_read",
    ),
    path("accounts/onboarding/", base.onboarding_modal, name="onboarding_modal"),
    path(
        "accounts/password/",
        base.change_password_modal,
        name="change_password_modal",
    ),
    path(
        "accounts/ajax/password/",
        ajax_actions.change_password,
        name="change_password",
    ),
    path("accounts/ajax/departments/", ajax_actions.departments, name="departments"),
    path("accounts/ajax/onboarding/", ajax_actions.onboarding, name="onboarding"),
    path(
        "accounts/ajax/push/subscribe/",
        ajax_actions.push_subscribe,
        name="push_subscribe",
    ),
    path(
        "accounts/ajax/push/unsubscribe/",
        ajax_actions.push_unsubscribe,
        name="push_unsubscribe",
    ),
    # PWA : service worker à la racine (scope « / ») + manifest au
    # type MIME officiel (critères d'installabilité Chrome/Edge/Safari).
    path("service-worker.js", base.service_worker, name="service_worker"),
    path("manifest.json", base.pwa_manifest, name="pwa_manifest"),
]
