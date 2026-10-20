"""
Vues HTML de accounts (pages et fragments servis dans la coque SPA).

Routage par rôle depuis `/dashboard/` : étudiant → flux, enseignant → inbox,
super-admin → console analytique. Le fragment initial et la bottom-nav sont
choisis côté serveur, jamais par un paramètre client.
"""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.db.models import Q
from django.http import FileResponse, Http404
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render

from accounts.decorators import login_required_json, student_required
from accounts.models import Faculty
from accounts.spa import is_fragment_request, render_dashboard_shell, spa_page
from accounts.utils import ROLE_STUDENT, role_name
from core_scolarite.models import Course, ServiceAssignment


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
    """Connexion : fragment pour la modale, page complète en accès direct.

    La modale AJAX injecte uniquement le corps du formulaire. Ouverte par
    URL directe (F5, favori, lien partagé), la même route doit renvoyer une
    page stylée : sinon le navigateur affiche un fragment brut, sans
    `<meta viewport>` ni feuille de style — illisible sur mobile.
    """
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    _prime_csrf_cookie(request)
    if is_fragment_request(request):
        return render(request, "modals/login.html")
    return render(request, "login/page.html")


def dashboard_shell(request):
    """Coque SPA : header + #spa-viewport + bottom nav, fragment initial par rôle."""
    if not request.user.is_authenticated:
        return redirect("accounts:landing")

    role = role_name(request.user)
    if role is None:
        # Compte authentifié sans profil métier : on referme la session proprement.
        auth_logout(request)
        return redirect("accounts:landing")

    _prime_csrf_cookie(request)
    # Fragment du rôle rendu et inliné côté serveur : affichage immédiat,
    # sans le fetch initial qui doublait le temps de chargement de la coque.
    return render_dashboard_shell(request)


@spa_page
@login_required_json
def profile_fragment(request):
    """Fragment du profil (bandeau « mot de passe géré par le portail central »)."""
    role = role_name(request.user)
    context = {"role": role}
    if role == ROLE_STUDENT:
        context["student"] = request.user.student_profile
    elif role == "teacher":
        teacher = request.user.teacher_profile
        context["teacher"] = teacher
        # Rattachements professionnels (B9) : cours dont il est responsable
        # ou affecté, et services dont il est membre actif.
        context["teacher_courses"] = (
            Course.objects.filter(
                Q(primary_instructor=teacher)
                | Q(assignments__teacher=teacher, assignments__is_active=True)
            )
            .distinct()
            .order_by("code")
        )
        context["teacher_services"] = (
            ServiceAssignment.objects.filter(user=request.user, is_active=True)
            .select_related("service")
            .order_by("service__name")
        )
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


def pwa_manifest(request):
    """
    Sert le manifest PWA avec le type MIME officiel.

    Chrome exige un manifest atteignable sans redirection depuis la page
    d'accueil ; le type `application/manifest+json` évite tout rejet selon
    le navigateur ou la chaîne de production (reverse-proxy, CDN…).
    """
    path = settings.BASE_DIR / "static" / "manifest.json"
    if not path.exists():
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="application/manifest+json")
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


@login_required_json
def change_password_modal(request):
    """Fragment de la modale « Changer mon mot de passe » (A6)."""
    return render(request, "modals/change_password.html")
