"""
Actions AJAX de accounts (JSON).

Phase 4 : login/logout, cascade Faculté → Département, onboarding MVP.
Règle IDOR : ces vues ne lisent jamais d'identifiant de profil côté client ;
l'onboarding écrit exclusivement sur `request.user.student_profile`.
"""

from datetime import datetime, timedelta
import json

from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import login_required_json, student_required
from accounts.forms import OnboardingForm
from accounts.models import Department
from accounts.services import webpush

# Rate-limit simple, stocké en session (§9.2) : 5 échecs → blocage 5 minutes.
MAX_LOGIN_ATTEMPTS = 5
LOCK_SECONDS = 300


def _error(message, status=400, **extra):
    payload = {"status": "error", "message": str(message)}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _role_name(user):
    """Rôle courant : 'admin', 'student', 'teacher' ou None."""
    if user.is_superuser:
        return "admin"
    if getattr(user, "student_profile", None) is not None:
        return "student"
    if getattr(user, "teacher_profile", None) is not None:
        return "teacher"
    return None


def _is_locked(request):
    until = request.session.get("login_lock_until")
    if not until:
        return False
    try:
        lock_until = datetime.fromisoformat(until)
    except (TypeError, ValueError):
        request.session.pop("login_lock_until", None)
        return False
    if timezone.is_naive(lock_until):
        lock_until = timezone.make_aware(lock_until, timezone.get_current_timezone())
    return timezone.now() < lock_until


def _register_failure(request):
    attempts = request.session.get("login_attempts", 0) + 1
    request.session["login_attempts"] = attempts
    if attempts >= MAX_LOGIN_ATTEMPTS:
        lock_until = timezone.now() + timedelta(seconds=LOCK_SECONDS)
        request.session["login_lock_until"] = lock_until.isoformat()
    return attempts


@require_POST
def login_view(request):
    """Authentification par matricule + mot de passe → JSON.

    Phase 4 : login/logout, cascade Faculté → Département, onboarding MVP.
    Règle IDOR : ces vues ne lisent jamais d'identifiant de profil côté client ;
    ongagement (ID) client est toujours ignoré côté serveur.

    La résolution du payload est explicite (§9.2) : on accepte deux variantes de
    champ HTML (`matricule` / `username`) afin de capter toutes les
    intégrations front, puis on transmet le login résolu directement sous le nom
    `username` à `authenticate()` : la `User.username` stocke bien le
    matricule généré par `seed_demo`.
    """
    if request.user.is_authenticated:
        return JsonResponse({"status": "success", "next": reverse("accounts:dashboard")})

    if _is_locked(request):
        return _error(_("Trop de tentatives. Réessayez dans quelques minutes."), status=429)

    # 1. Résolution du payload
    matricule = request.POST.get("matricule")
    if not matricule:
        matricule = request.POST.get("username")
    password = request.POST.get("password")

    # 2. Validation des champs obligatoires
    if not matricule or not password:
        attempts = _register_failure(request)
        return _error(
            _("Matricule et mot de passe sont requis. Saisissez vos deux identifiants."),
            status=400,
            attempts=attempts,
        )

    # 3. Authentification stricte : username=matricule (donnée brute, tel quel)
    user = authenticate(request, username=matricule, password=password)

    if user is None:
        _register_failure(request)
        return _error(_("Matricule ou mot de passe incorrect."), status=401)

    if not user.is_active:
        _register_failure(request)
        return _error(_("Ce compte est désactivé."), status=401)

    # 4. Connexion et session
    auth_login(request, user)
    request.session.pop("login_attempts", None)
    request.session.pop("login_lock_until", None)

    # 5. Rôle + payload
    role = _role_name(user)
    return JsonResponse(
        {
            "status": "success",
            "user_type": role,
            "next": reverse("accounts:dashboard"),
        }
    )


@require_POST
@login_required_json
def logout_view(request):
    auth_logout(request)
    return JsonResponse(
        {"status": "success", "next": reverse("accounts:landing")}
    )


@require_GET
@login_required_json
def departments(request):
    """Cascade : départements d'une faculté (jamais d'ID de profil client)."""
    faculty_id = request.GET.get("faculty")
    if not faculty_id:
        return JsonResponse({"status": "success", "departments": []})
    queryset = (
        Department.objects.filter(
            faculty_id=faculty_id, is_active=True, faculty__is_active=True
        )
        .values("id", "name")
        .order_by("name")
    )
    return JsonResponse({"status": "success", "departments": list(queryset)})


@require_POST
@student_required
def onboarding(request):
    """Complète le profil de l'étudiant connecté (Cas A)."""
    form = OnboardingForm(data=request.POST, student=request.student)
    if not form.is_valid():
        errors = [str(err) for errs in form.errors.values() for err in errs]
        return _error(" ".join(errors), status=400)
    form.save()
    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Profil complété avec succès.")),
            "next": reverse("accounts:dashboard"),
        }
    )


@require_POST
@login_required_json
def change_password(request):
    """
    Changement de mot de passe de l'utilisateur connecté (A6).

    Contrôles : mot actuel vérifié, nouveau mot de passe conforme (8 car. min.)
    et confirmation identique. Le mot de passe n'est jamais journalisé.
    """
    current = request.POST.get("current_password") or ""
    new1 = request.POST.get("new_password1") or ""
    new2 = request.POST.get("new_password2") or ""

    if not current or not new1 or not new2:
        return _error(
            _("Tous les champs sont obligatoires."),
            errors={
                "current_password": str(_("Champ obligatoire.")) if not current else "",
                "new_password1": str(_("Champ obligatoire.")) if not new1 else "",
                "new_password2": str(_("Champ obligatoire.")) if not new2 else "",
            },
        )
    if not request.user.check_password(current):
        return _error(
            _("Mot de passe actuel incorrect."),
            errors={"current_password": str(_("Mot de passe incorrect."))},
        )
    if len(new1) < 8:
        return _error(
            _("Le nouveau mot de passe doit contenir au moins 8 caractères."),
            errors={"new_password1": str(_("Minimum 8 caractères."))},
        )
    if new1 != new2:
        return _error(
            _("Les deux nouveaux mots de passe ne correspondent pas."),
            errors={"new_password2": str(_("Les mots de passe ne correspondent pas."))},
        )

    request.user.set_password(new1)
    request.user.save(update_fields=["password"])
    # La session conserve l'utilisateur connecté après rotation du hash.
    request.session.cycle_key()
    return JsonResponse(
        {"status": "success", "message": _("Mot de passe modifié avec succès.")}
    )


@require_POST
@login_required_json
def push_subscribe(request):
    """Enregistre un abonnement Web Push pour l'utilisateur connecté."""
    if not webpush.is_configured():
        return _error(_("Notifications push non configurées sur ce serveur."), status=503)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return _error(_("Corps JSON invalide."))
    subscription = payload.get("subscription")
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return _error(_("Abonnement push invalide."))
    try:
        webpush.save_subscription(request.user, subscription)
    except ValueError:
        return _error(_("Abonnement push invalide."))
    return JsonResponse(
        {"status": "success", "message": str(_("Notifications activées."))}
    )


@require_POST
@login_required_json
def push_unsubscribe(request):
    """Supprime un abonnement push — uniquement celui de l'utilisateur connecté."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return _error(_("Corps JSON invalide."))
    subscription = payload.get("subscription") or {}
    endpoint = subscription.get("endpoint")
    if isinstance(subscription, dict) and endpoint:
        webpush.remove_subscription(request.user, subscription)
    return JsonResponse(
        {"status": "success", "message": str(_("Notifications désactivées."))}
    )
