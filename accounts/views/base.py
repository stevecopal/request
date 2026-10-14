"""
Vues HTML de accounts (pages et fragments servis dans la coque SPA).

Routage par rôle depuis `/dashboard/` : étudiant → flux, enseignant → inbox,
super-admin → console analytique. Le fragment initial et la bottom-nav sont
choisis côté serveur, jamais par un paramètre client.
"""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.http import FileResponse, Http404
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from accounts.decorators import login_required_json, student_required
from accounts.models import Faculty
from accounts.utils import (
    ROLE_STUDENT,
    nav_items,
    role_dashboard_url,
    role_name,
)


def _prime_csrf_cookie(request):
    """Pose le cookie csrftoken (lu ensuite par app_spa.js pour les POST AJAX)."""
    get_token(request)


def landing_page(request):
    """Landing minimaliste — redirige les utilisateurs déjà connectés."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    _prime_csrf_cookie(request)
    return render(request, "landing/index.html")


def login_fragment(request):
    """Fragment du corps de la modale de connexion (injecté dans #modal-body)."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    _prime_csrf_cookie(request)
    return render(request, "modals/login.html")


def dashboard_shell(request):
    """Coque SPA : header + #spa-viewport + bottom nav, fragment initial par rôle."""
    if not request.user.is_authenticated:
        return redirect("accounts:landing")

    role = role_name(request.user)
    if role is None:
        # Compte authentifié sans profil métier : on referme la session proprement.
        auth_logout(request)
        return redirect("accounts:landing")

    needs_onboarding = (
        role == ROLE_STUDENT and not request.user.student_profile.is_onboarded
    )

    _prime_csrf_cookie(request)
    unread_notifications = 0
    if role in (ROLE_STUDENT, "teacher"):
        from accounts.models import Notification

        unread_notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
    context = {
        "role": role,
        "nav_items": nav_items(role, unread_notifications=unread_notifications),
        "unread_notifications": unread_notifications,
        "initial_fragment": reverse(role_dashboard_url(role)),
        "needs_onboarding": needs_onboarding,
        "onboarding_modal": reverse("accounts:onboarding_modal"),
    }
    return render(request, "dashboard/index.html", context)


@login_required_json
def profile_fragment(request):
    """Fragment du profil (bandeau « mot de passe géré par le portail central »)."""
    role = role_name(request.user)
    context = {"role": role}
    if role == ROLE_STUDENT:
        context["student"] = request.user.student_profile
    elif role == "teacher":
        context["teacher"] = request.user.teacher_profile
    return render(request, "partials/profile.html", context)


def service_worker(request):
    """Sert le service worker à la racine pour lui donner le scope « / »."""
    path = settings.BASE_DIR / "static" / "service-worker.js"
    if not path.exists():
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@student_required
def onboarding_modal(request):
    """Fragment de la modale d'onboarding (cascade Faculté → Département)."""
    return render(
        request,
        "modals/onboarding_profile.html",
        {
            "faculties": Faculty.objects.only("id", "name").order_by("name"),
            "student": request.student,
        },
    )
