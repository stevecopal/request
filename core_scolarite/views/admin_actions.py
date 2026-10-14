"""
Actions d'administration — core_scolarite.

`admin_import_upload` : reçoit un fichier multipart (CSV/XLSX) et le passe au
service ETL. Réponse JSON : succès `{status, imported_count}` ou erreurs
détaillées `{status, message, errors:[{line, message}]}`. Accès superuser strict.
"""

from datetime import date

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from django.contrib.auth.models import User
from django.db import transaction

from accounts.decorators import superuser_required
from accounts.models import Student, Teacher
from core_scolarite.forms import ManualAccountForm
from core_scolarite.services.data_importer import ImportValidationError, import_users

ALLOWED_EXTENSIONS = ("csv", "xlsx")


@require_POST
@superuser_required
def admin_import_upload(request):
    """Traite l'upload d'un fichier de population (étudiants ou enseignants)."""
    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Aucun fichier reçu."))}, status=400
        )

    name = upload.name.lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        return JsonResponse(
            {
                "status": "error",
                "message": str(_("Format non supporté : utilisez un fichier .csv ou .xlsx.")),
            },
            status=400,
        )

    entity = request.POST.get("entity", "students")
    # `strict_placement` : case cochée ⇒ rattachement faculté/département exigé.
    strict_placement = request.POST.get("strict_placement") in ("true", "on", "1")
    # Université cible de l'import (défaut : université par défaut configurée).
    university = request.POST.get("university") or None

    try:
        imported_count = import_users(
            upload,
            entity=entity,
            strict_placement=strict_placement,
            university=university,
        )
    except ImportValidationError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": exc.message,
                "errors": exc.errors,
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Import réussi.")),
            "imported_count": imported_count,
        }
    )


@require_POST
@superuser_required
def admin_create_account(request):
    """Création manuelle d'un compte étudiant/enseignant (option A du brief)."""
    form = ManualAccountForm(data=request.POST)
    if not form.is_valid():
        errors = [
            {"line": field, "message": " ".join(messages)}
            for field, messages in form.errors.items()
        ]
        return JsonResponse(
            {
                "status": "error",
                "message": str(_("Formulaire invalide.")),
                "errors": errors,
            },
            status=400,
        )

    data = form.cleaned_data
    entity = data["entity"]
    year = date.today().year
    pattern = settings.IMPORT_DEFAULT_PASSWORD_PATTERN

    with transaction.atomic():
        user = User.objects.create(
            username=data["matricule"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
        )
        user.set_password(pattern.format(matricule=data["matricule"], year=year))
        user.save(update_fields=["password"])

        if entity == "students":
            Student.objects.create(
                user=user,
                registration_number=data["matricule"],
                faculty=data["faculty"],
                department=data["department"],
            )
        else:
            Teacher.objects.create(
                user=user,
                title=data["title"],
                faculty=data["faculty"],
                department=data["department"],
            )

    return JsonResponse(
        {"status": "success", "message": str(_("Compte créé avec succès."))}
    )
