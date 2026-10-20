"""
Actions d'administration — core_scolarite.

  POST admin/import/preview/    aperçu ETL : validation + rapport ligne à ligne
  POST admin/import/commit/     confirmation d'écriture (jeton signé, usage unique)
  GET  admin/import/template/   modèle CSV/XLSX prérempli des en-têtes requis
  POST admin/import/upload/     import direct (API historique, validate-then-create)
  POST admin/accounts/create/   création manuelle (matricule auto-généré)

Règles appliquées (brief §1, §2, §4) :
  * matricule généré automatiquement au format `CM-UDS-22SCI0001`, sans
    collision (comptes manuels) ; matricules du fichier validés (format +
    cohérence faculté) ;
  * aucun mot de passe en clair : mot de passe aléatoire non communiqué, les
    comptes démarrent **inactifs** et s'activent à la première connexion
    (lien à usage unique) ou par émission d'accès super-admin ;
  * rapport détaillé par ligne avant toute écriture, écriture atomique,
    contrôle explicite pour n'enregistrer que les lignes valides ;
  * journalisation (audit) des aperçus, imports, corrections et créations.
"""

from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from accounts.decorators import superuser_required
from accounts.models import University
from accounts.services import matricules
from core_scolarite.forms import ManualAccountForm
from core_scolarite.services import audit as audit_service
from core_scolarite.services.credentials import set_random_password
from core_scolarite.services.data_importer import (
    HEADERS_BY_ENTITY,
    ImportValidationError,
    commit_import,
    import_users,
    preview_import,
    resolve_university,
)

from .common import json_error, json_ok

ALLOWED_EXTENSIONS = ("csv", "xlsx")
CREATION_ATTEMPTS = 5

TEMPLATE_HELP = {
    "students": [
        "Modèle d'import des étudiants — UnivReq.",
        "En-têtes requis (ligne 1, dans cet ordre) : MATRICULE, NOM, PRENOM, EMAIL, FACULTE, DEPARTEMENT.",
        "MATRICULE : format officiel CM-UDS-22SCI0001 (pays, université, année, code faculté, numéro d'ordre).",
        "FACULTE / DEPARTEMENT : intitulés exacts configurés dans la console (C2 → Organisation).",
        "Unicité des matricules et des adresses e-mail vérifiée dans le fichier et en base.",
        "Comptes créés inactifs : chaque utilisateur s'active avec le lien de première connexion.",
    ],
    "teachers": [
        "Modèle d'import des enseignants — UnivReq.",
        "En-têtes requis (ligne 1, dans cet ordre) : MATRICULE, NOM, PRENOM, EMAIL, FACULTE, DEPARTEMENT.",
        "MATRICULE enseignant : format CM-UDS-22ENS0001 (segment enseignant configuré côté serveur).",
        "FACULTE / DEPARTEMENT : intitulés exacts configurés dans la console (C2 → Organisation).",
        "Unicité des matricules et des adresses e-mail vérifiée dans le fichier et en base.",
        "Comptes créés inactifs : chaque utilisateur s'active avec le lien de première connexion.",
    ],
}


def _check_upload(upload):
    """Contrôle du fichier reçu (présence, extension). Renvoie une erreur JSON."""
    if upload is None:
        return json_error(_("Aucun fichier reçu."), status=400)
    name = upload.name.lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        return json_error(
            _("Format non supporté : utilisez un fichier .csv ou .xlsx."), status=400
        )
    return None


def _import_options(request) -> dict:
    """Paramètres d'import communs (entité, rattachement strict, université)."""
    entity = request.POST.get("entity", "students")
    return {
        "entity": entity,
        # `strict_placement` : case cochée ⇒ rattachement faculté/département exigé.
        "strict_placement": request.POST.get("strict_placement") in ("true", "on", "1"),
        "university": request.POST.get("university") or None,
    }


def _audit_university(pk):
    """Université cible pour l'audit (None si introuvable — jamais d'erreur)."""
    return University.objects.filter(pk=pk).first()


# --------------------------------------------------------------------------- #
# Import — phase 1 : aperçu (rapport ligne à ligne, aucune écriture)
# --------------------------------------------------------------------------- #

@require_POST
@superuser_required
def admin_import_preview(request):
    """Valide le fichier et renvoie le rapport (erreurs, doublons, échantillon)."""
    upload = request.FILES.get("file")
    error = _check_upload(upload)
    if error is not None:
        return error

    options = _import_options(request)
    try:
        report = preview_import(upload, **options)
    except ImportValidationError as exc:
        return JsonResponse(
            {"status": "error", "message": exc.message, "errors": exc.errors},
            status=400,
        )

    audit_service.record(
        request,
        "import",
        model_label="core_scolarite.ImportPreview",
        changes={
            "entity": report["entity"],
            "total": report["total"],
            "valid": report["valid"],
            "errors": len(report["errors"]),
            "duplicates": len(report["duplicates"]),
            "stage": "preview",
        },
        university=_audit_university(report["university"]),
    )
    return JsonResponse({"status": "success", **report})


# --------------------------------------------------------------------------- #
# Import — phase 2 : confirmation d'écriture (jeton signé d'aperçu)
# --------------------------------------------------------------------------- #

@require_POST
@superuser_required
def admin_import_commit(request):
    """Écrit les lignes validées par l'aperçu (transaction atomique unique)."""
    token = (request.POST.get("token") or "").strip()
    if not token:
        return json_error(_("Aperçu manquant : rechargez le fichier."), status=400)
    skip_invalid = request.POST.get("skip_invalid") in ("true", "on", "1")

    try:
        result = commit_import(
            token,
            university=request.POST.get("university") or None,
            actor=request.user,
            skip_invalid=skip_invalid,
        )
    except ImportValidationError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": exc.message,
                "errors": exc.errors,
                "duplicates": exc.duplicates,
            },
            status=400,
        )

    audit_service.record(
        request,
        "import",
        model_label="core_scolarite.Import",
        changes={
            "entity": result["entity"],
            "imported": result["imported"],
            "skipped": result.get("skipped", 0),
            "stage": "commit",
        },
        university=_audit_university(result["university"]),
    )
    return json_ok(
        _("%(imported)s compte(s) créé(s)%(extra)s.")
        % {
            "imported": result["imported"],
            "extra": (
                _(", %(skipped)s ligne(s) ignorée(s)")
                % {"skipped": result.get("skipped", 0)}
                if result.get("skipped")
                else ""
            ),
        },
        imported_count=result["imported"],
        skipped=result.get("skipped", 0),
    )


# --------------------------------------------------------------------------- #
# Modèle d'import (en-têtes requis) — CSV ou XLSX
# --------------------------------------------------------------------------- #

@require_GET
@superuser_required
def admin_import_template(request):
    """Télécharge le modèle prérempli des en-têtes requis (CSV ou XLSX)."""
    entity = request.GET.get("entity", "students")
    if entity not in ("students", "teachers"):
        entity = "students"
    as_xlsx = request.GET.get("format", "csv").lower() == "xlsx"
    headers = HEADERS_BY_ENTITY[entity]
    help_lines = TEMPLATE_HELP[entity]

    if as_xlsx:
        from io import BytesIO

        from openpyxl import Workbook

        buffer = BytesIO()        
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Import"
        sheet.append(headers)
        for index in range(len(headers)):
            sheet.column_dimensions[chr(ord("A") + index)].width = 18
        help_sheet = workbook.create_sheet("Aide")
        for line in help_lines:
            help_sheet.append([line])
        help_sheet.column_dimensions["A"].width = 110
        workbook.save(buffer)
        payload, content_type, extension = (
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    else:
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        payload = "﻿" + buffer.getvalue()
        payload, content_type, extension = payload.encode("utf-8"), "text/csv", "csv"

    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="modele-import-{entity}.{extension}"'
    )
    audit_service.record(
        request,
        "export",
        model_label="core_scolarite.ImportTemplate",
        changes={"entity": entity, "format": extension},
    )
    return response


# --------------------------------------------------------------------------- #
# Import — API historique (validate-then-create en une seule passe)
# --------------------------------------------------------------------------- #

@require_POST
@superuser_required
def admin_import_upload(request):
    """Traite l'upload d'un fichier de population (étudiants ou enseignants)."""
    upload = request.FILES.get("file")
    error = _check_upload(upload)
    if error is not None:
        return error

    options = _import_options(request)
    try:
        imported_count = import_users(upload, **options)
    except ImportValidationError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": exc.message,
                "errors": exc.errors,
                "duplicates": exc.duplicates,
            },
            status=400,
        )

    target = resolve_university(options["university"])
    audit_service.record(
        request,
        "import",
        model_label="core_scolarite.Import",
        changes={"entity": options["entity"], "imported": imported_count},
        university=target,
    )
    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Import réussi.")),
            "imported_count": imported_count,
        }
    )


# --------------------------------------------------------------------------- #
# Création manuelle d'un compte
# --------------------------------------------------------------------------- #

@require_POST
@superuser_required
def admin_create_account(request):
    """
    Création manuelle d'un compte étudiant/enseignant (option A du brief).

    * matricule saisi → validé (format officiel + cohérence faculté/segment) ;
    * matricule vide → généré automatiquement sans collision
      (`CM-UDS-25SCI0001` étudiant, `CM-UDS-25ENS0001` enseignant) ;
    * le compte démarre inactif : l'accès s'ouvre par le lien de première
      connexion ou par émission d'accès super-admin (aucun mot de passe en clair).
    """
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
    faculty = data["faculty"]

    user = None
    for attempt in range(CREATION_ATTEMPTS):
        try:
            with transaction.atomic():
                # Matricule saisi ou généré (sans collision, reprise sur conflit).
                matricule = data["matricule"] or matricules.generate(faculty, entity)
                user = User.objects.create(
                    username=matricule,
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    email=data["email"],
                    # Inactif jusqu'à la première connexion (lien à usage unique).
                    is_active=False,
                )
                # Jamais de mot de passe par défaut prévisible : aléatoire non communiqué.
                set_random_password(user)

                if entity == "students":
                    from accounts.models import Student

                    Student.objects.create(
                        user=user,
                        registration_number=matricule,
                        faculty=data["faculty"],
                        department=data["department"],
                    )
                else:
                    from accounts.models import Teacher

                    Teacher.objects.create(
                        user=user,
                        title=data["title"],
                        faculty=data["faculty"],
                        department=data["department"],
                    )
            break
        except IntegrityError:
            # Conflit d'unicité : reproducible seulement si le matricule a été
            # saisi (déjà contrôlé) ; sinon on relance une génération.
            if data["matricule"] or attempt == CREATION_ATTEMPTS - 1:
                return json_error(
                    _("Ce matricule vient d'être attribué à un autre compte. "
                      "Réessayez."),
                    status=409,
                )

    audit_service.record(
        request,
        "create",
        obj=user,
        changes={
            "username": user.username,
            "entity": entity,
            "generated_matricule": not bool(data["matricule"]),
            "faculty": data["faculty"].name,
            "department": getattr(data["department"], "name", ""),
        },
        university=faculty.university,
    )

    return json_ok(
        _(
            "Compte %(matricule)s créé (inactif). Envoyez le lien de première "
            "connexion ou émettez un accès pour l'activer."
        )
        % {"matricule": user.username},
        matricule=user.username,
    )
