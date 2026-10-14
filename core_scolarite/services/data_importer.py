"""
Service d'import massif (ETL) — core_scolarite (ARCHITECTURE §8.1).

Contrat (durci pour la console SuperAdmin) :
  * **Deux phases** : `preview_import()` valide sans écrire et retourne un
    rapport (aperçu, doublons, erreurs ligne à ligne) ; `commit_import()`
    rejoue la validation sur les données stockées puis écrit **une seule fois**,
    dans une transaction atomique. Aucune écriture partielle, jamais.
  * Entités supportées : `students`, `teachers`, `enrollments` (affectation
    étudiant → cours) et `course_assignments` (affectation enseignant → cours).
  * Isolation multi-universités : les références (faculté, département, cours,
    enseignant, étudiant) sont résolues **dans l'université cible uniquement**.
  * Aucun mot de passe en clair importable : les comptes sont créés avec un
    mot de passe aléatoire non communiqué (voir `services.credentials`).

Format : `.csv` (utf-8-sig) ou `.xlsx` (openpyxl) ; en-têtes comparés de façon
insensible à la casse et aux espaces.
"""

from __future__ import annotations

import secrets
import uuid as uuid_lib
from datetime import date
from typing import Literal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from openpyxl import load_workbook

from accounts.models import (
    AcademicYear,
    Department,
    Faculty,
    Student,
    Teacher,
    University,
)
from core_scolarite.models import Course, CourseAssignment, Enrollment

from .credentials import set_random_password

Entity = Literal["students", "teachers", "enrollments", "course_assignments"]

# Durée de validité d'un aperçu (le token d'import expire ensuite).
PREVIEW_TTL_SECONDS = 900
PREVIEW_SAMPLE_SIZE = 50

ENTITY_LABELS: dict[str, str] = {
    "students": "Étudiants",
    "teachers": "Enseignants",
    "enrollments": "Inscriptions (étudiant → cours)",
    "course_assignments": "Affectations (enseignant → cours)",
}

HEADERS_BY_ENTITY: dict[str, list[str]] = {
    "students": ["MATRICULE", "NOM", "PRENOM", "EMAIL", "FACULTE", "DEPARTEMENT"],
    "teachers": ["MATRICULE", "NOM", "PRENOM", "EMAIL", "FACULTE", "DEPARTEMENT"],
    "enrollments": ["MATRICULE", "CODE_COURS", "ANNEE"],
    "course_assignments": ["MATRICULE", "CODE_COURS", "ANNEE", "ACTIF"],
}

# « ACTIF » est facultatif (défaut : oui).
OPTIONAL_HEADERS: dict[str, list[str]] = {"course_assignments": ["ACTIF"]}

# Rétro-compatibilité : en-têtes historiques du seul import « users ».
REQUIRED_HEADERS = HEADERS_BY_ENTITY["students"]

TRUE_VALUES = {"1", "true", "oui", "o", "yes", "y", "vrai"}
FALSE_VALUES = {"0", "false", "non", "n", "no", "faux"}


class ImportValidationError(Exception):
    """Erreur d'import bloquante (en-tête manquant, erreurs ou doublons)."""

    def __init__(self, message: str, errors: list[dict] | None = None,
                 duplicates: list[dict] | None = None):
        self.message = str(message)
        self.errors = errors or []
        self.duplicates = duplicates or []
        super().__init__(self.message)


def resolve_university(university=None) -> University:
    """
    Résout l'université cible de l'import.

    * instance fournie → utilisée telle quelle ;
    * UUID fourni → recherchée (introuvable → erreur) ;
    * aucun → l'université par défaut (la seule, ou la première par nom).
    """
    if isinstance(university, University):
        return university
    if university:
        found = University.objects.filter(pk=university).first()
        if found is None:
            raise ImportValidationError(_("Université introuvable."))
        return found
    default = University.objects.order_by("name").first()
    if default is None:
        raise ImportValidationError(
            _("Aucune université configurée : créez-en une avant l'import.")
        )
    return default


def _normalize_headers(raw_headers) -> list[str]:
    return [(str(h) if h is not None else "").strip().upper() for h in raw_headers]


def _check_headers(entity: str, headers: list[str]) -> None:
    required = [
        header
        for header in HEADERS_BY_ENTITY[entity]
        if header not in OPTIONAL_HEADERS.get(entity, [])
    ]
    missing = [header for header in required if header not in headers]
    if missing:
        raise ImportValidationError(
            _("Colonne(s) manquante(s) dans l'en-tête : %(missing)s. En-têtes attendus : %(all)s.")
            % {"missing": ", ".join(missing), "all": ", ".join(HEADERS_BY_ENTITY[entity])}
        )


def _tabular_rows(rows_source):
    """Consomme les en-têtes puis renvoie (en-têtes, lignes) normalisés."""
    iterator = iter(rows_source)
    try:
        raw_headers = next(iterator)
    except StopIteration:
        raise ImportValidationError(_("Le fichier est vide."))
    headers = _normalize_headers(raw_headers)

    data: list[tuple[int, dict]] = []
    for line_number, values in enumerate(iterator, start=2):
        if values is None:
            continue
        values = list(values)
        if all(value is None or str(value).strip() == "" for value in values):
            continue  # ignore les lignes totalement vides
        record = {}
        for index, header in enumerate(headers):
            value = values[index] if index < len(values) else None
            record[header] = str(value).strip() if value is not None else ""
        data.append((line_number, record))
    return headers, data


def _load_rows(source, name: str):
    """(en-têtes, lignes) selon l'extension du fichier."""
    lower = name.lower()
    if lower.endswith(".csv"):
        import csv
        import io

        text = source.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8-sig")
        return _tabular_rows(csv.reader(io.StringIO(text)))
    if lower.endswith(".xlsx"):
        workbook = load_workbook(source, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            return _tabular_rows(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
    raise ImportValidationError(
        _("Format de fichier non supporté : utilisez un fichier .csv ou .xlsx.")
    )


def _is_valid_email(value: str) -> bool:
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import validate_email

    try:
        validate_email(value)
        return True
    except DjangoValidationError:
        return False


# --------------------------------------------------------------------------- #
# Validation ligne à ligne (sans aucune écriture)
# --------------------------------------------------------------------------- #
def _validate_users(records, *, strict_placement: bool, university: University):
    """Valide des comptes étudiants/enseignants ; retourne le rapport."""
    faculties = {
        (faculty.university_id, faculty.name.strip().upper()): faculty
        for faculty in Faculty.objects.filter(university=university)
    }
    departments = {
        (department.faculty_id, department.name.strip().upper()): department
        for department in Department.objects.filter(faculty__university=university)
    }
    existing_matricules = set(
        User.objects.filter(username__in=[r.get("MATRICULE", "") for _, r in records])
        .values_list("username", flat=True)
    )

    rows, errors, duplicates = [], [], []
    seen_matricules: set[str] = set()
    seen_emails: set[str] = set()

    for line_number, record in records:
        matricule = (record.get("MATRICULE") or "").strip()
        nom = (record.get("NOM") or "").strip()
        prenom = (record.get("PRENOM") or "").strip()
        email = (record.get("EMAIL") or "").strip()
        faculty_name = (record.get("FACULTE") or "").strip()
        department_name = (record.get("DEPARTEMENT") or "").strip()

        line_errors: list[str] = []
        if not matricule:
            line_errors.append(_("MATRICULE vide."))
        if not nom:
            line_errors.append(_("NOM vide."))
        if not prenom:
            line_errors.append(_("PRENOM vide."))
        if not email:
            line_errors.append(_("EMAIL vide."))
        elif not _is_valid_email(email):
            line_errors.append(_("EMAIL invalide : %(email)s.") % {"email": email})

        is_duplicate = False
        if matricule:
            if matricule in existing_matricules:
                is_duplicate = True
                duplicates.append(
                    {"line": line_number, "identifier": matricule,
                     "reason": _("Matricule déjà existant.")}
                )
            elif matricule in seen_matricules:
                is_duplicate = True
                duplicates.append(
                    {"line": line_number, "identifier": matricule,
                     "reason": _("Matricule en doublon dans le fichier.")}
                )
            else:
                seen_matricules.add(matricule)
        if email:
            key = email.casefold()
            if key in seen_emails:
                line_errors.append(_("EMAIL en doublon dans le fichier : %(email)s.") % {"email": email})
            seen_emails.add(key)

        # Résolution hiérarchique faculté → département (université cible).
        faculty = department = None
        if faculty_name:
            faculty = faculties.get((university.pk, faculty_name.upper()))
            if faculty is None:
                line_errors.append(
                    _("FACULTE inexistante dans « %(uni)s » : %(name)s.")
                    % {"uni": university.name, "name": faculty_name}
                )
        elif strict_placement:
            line_errors.append(_("FACULTE vide."))

        if department_name:
            if faculty is None:
                line_errors.append(
                    _("DEPARTEMENT « %(name)s » sans FACULTE valide.")
                    % {"name": department_name}
                )
            else:
                department = departments.get((faculty.pk, department_name.upper()))
                if department is None:
                    line_errors.append(
                        _("DEPARTEMENT « %(name)s » non rattaché à « %(faculty)s ».")
                        % {"name": department_name, "faculty": faculty.name}
                    )
        elif strict_placement:
            line_errors.append(_("DEPARTEMENT vide."))

        if line_errors:
            errors.append(
                {"line": line_number, "message": " ".join(str(m) for m in line_errors)}
            )
        elif not is_duplicate:
            rows.append(
                {
                    "line": line_number,
                    "MATRICULE": matricule,
                    "NOM": nom,
                    "PRENOM": prenom,
                    "EMAIL": email,
                    "faculty_id": str(faculty.pk) if faculty else "",
                    "department_id": str(department.pk) if department else "",
                }
            )

    return rows, errors, duplicates


def _validate_enrollments(records, *, university: University):
    students = {
        s.registration_number.upper(): s
        for s in Student.objects.filter(faculty__university=university).select_related(
            "faculty"
        )
    }
    courses = {
        c.code.upper(): c
        for c in Course.objects.filter(
            department__faculty__university=university
        ).select_related("department__faculty")
    }
    years = {y.code.upper(): y for y in AcademicYear.objects.all()}
    existing = {
        (student_id, course_id)
        for student_id, course_id in Enrollment.objects.values_list(
            "student_id", "course_id"
        )
    }

    rows, errors, duplicates = [], [], []
    seen: set[tuple[str, str]] = set()

    for line_number, record in records:
        matricule = (record.get("MATRICULE") or "").strip()
        course_code = (record.get("CODE_COURS") or "").strip()
        year_code = (record.get("ANNEE") or "").strip()
        line_errors: list[str] = []

        student = students.get(matricule.upper()) if matricule else None
        if not matricule:
            line_errors.append(_("MATRICULE vide."))
        elif student is None:
            line_errors.append(
                _("Étudiant introuvable dans « %(uni)s » : %(matricule)s.")
                % {"uni": university.name, "matricule": matricule}
            )

        course = courses.get(course_code.upper()) if course_code else None
        if not course_code:
            line_errors.append(_("CODE_COURS vide."))
        elif course is None:
            line_errors.append(
                _("Cours introuvable dans « %(uni)s » : %(code)s.")
                % {"uni": university.name, "code": course_code}
            )

        year = years.get(year_code.upper()) if year_code else None
        if not year_code:
            line_errors.append(_("ANNEE vide."))
        elif year is None:
            line_errors.append(_("Année académique inexistante : %(code)s.") % {"code": year_code})

        is_duplicate = False
        if student and course:
            key = (str(student.pk), str(course.pk))
            if key in existing or key in seen:
                is_duplicate = True
                duplicates.append(
                    {"line": line_number, "identifier": f"{matricule} → {course_code}",
                     "reason": _("Inscription déjà existante.")}
                )
            seen.add(key)
            if (
                student.faculty_id
                and course.department.faculty_id != student.faculty_id
            ):
                line_errors.append(
                    _("Le cours appartient à une autre faculté que l'étudiant.")
                )

        if line_errors:
            errors.append(
                {"line": line_number, "message": " ".join(str(m) for m in line_errors)}
            )
        elif not is_duplicate:
            rows.append(
                {
                    "line": line_number,
                    "student_id": str(student.pk),
                    "course_id": str(course.pk),
                    "academic_year_id": str(year.pk),
                    "academic_year": year.code,
                }
            )

    return rows, errors, duplicates


def _validate_assignments(records, *, university: University):
    teachers = {
        t.user.username.upper(): t
        for t in Teacher.objects.filter(faculty__university=university).select_related(
            "user", "faculty", "department"
        )
    }
    courses = {
        c.code.upper(): c
        for c in Course.objects.filter(
            department__faculty__university=university
        ).select_related("department__faculty")
    }
    years = {y.code.upper(): y for y in AcademicYear.objects.all()}
    # (course, année) → affectation active existante
    active_by_course_year = {
        (str(row["course_id"]), str(row["academic_year_id"])): row["teacher_id"]
        for row in CourseAssignment.objects.filter(
            is_active=True, course__department__faculty__university=university
        ).values("course_id", "academic_year_id", "teacher_id")
    }

    rows, errors, duplicates = [], [], []
    seen: set[tuple[str, str]] = set()

    for line_number, record in records:
        matricule = (record.get("MATRICULE") or "").strip()
        course_code = (record.get("CODE_COURS") or "").strip()
        year_code = (record.get("ANNEE") or "").strip()
        raw_active = (record.get("ACTIF") or "").strip().lower()
        line_errors: list[str] = []

        teacher = teachers.get(matricule.upper()) if matricule else None
        if not matricule:
            line_errors.append(_("MATRICULE vide."))
        elif teacher is None:
            line_errors.append(
                _("Enseignant introuvable dans « %(uni)s » : %(matricule)s.")
                % {"uni": university.name, "matricule": matricule}
            )

        course = courses.get(course_code.upper()) if course_code else None
        if not course_code:
            line_errors.append(_("CODE_COURS vide."))
        elif course is None:
            line_errors.append(
                _("Cours introuvable dans « %(uni)s » : %(code)s.")
                % {"uni": university.name, "code": course_code}
            )

        year = years.get(year_code.upper()) if year_code else None
        if not year_code:
            line_errors.append(_("ANNEE vide."))
        elif year is None:
            line_errors.append(_("Année académique inexistante : %(code)s.") % {"code": year_code})

        active = True
        if raw_active:
            if raw_active in TRUE_VALUES:
                active = True
            elif raw_active in FALSE_VALUES:
                active = False
            else:
                line_errors.append(_("Valeur ACTIF invalide : %(value)s.") % {"value": raw_active})

        is_duplicate = False
        if teacher and course:
            if teacher.department_id != course.department_id:
                line_errors.append(
                    _("L'enseignant n'appartient pas au département du cours.")
                )
            key = (str(course.pk), str(year.pk) if year else "")
            if key in seen:
                is_duplicate = True
                duplicates.append(
                    {"line": line_number, "identifier": f"{matricule} → {course_code}",
                     "reason": _("Affectation en doublon dans le fichier.")}
                )
            seen.add(key)
            existing_teacher = active_by_course_year.get(key)
            if existing_teacher and active:
                if str(existing_teacher) == str(teacher.pk):
                    is_duplicate = True
                    duplicates.append(
                        {"line": line_number, "identifier": f"{matricule} → {course_code}",
                         "reason": _("Affectation active déjà existante.")}
                    )
                else:
                    line_errors.append(
                        _("Un responsable actif existe déjà pour ce cours et cette année.")
                    )

        if line_errors:
            errors.append(
                {"line": line_number, "message": " ".join(str(m) for m in line_errors)}
            )
        elif not is_duplicate:
            rows.append(
                {
                    "line": line_number,
                    "teacher_id": str(teacher.pk),
                    "course_id": str(course.pk),
                    "academic_year_id": str(year.pk),
                    "active": active,
                }
            )

    return rows, errors, duplicates


def _validate(entity: str, records, *, strict_placement: bool, university: University):
    """Validation complète du fichier ; rapport sans écriture."""
    if entity == "students":
        # Mode MVP possible : faculté/département tolérés (profil non onboardé).
        return _validate_users(
            records, strict_placement=strict_placement, university=university
        )
    if entity == "teachers":
        # Les enseignants exigent toujours un rattachement complet.
        return _validate_users(records, strict_placement=True, university=university)
    if entity == "enrollments":
        return _validate_enrollments(records, university=university)
    if entity == "course_assignments":
        return _validate_assignments(records, university=university)
    raise ImportValidationError(
        _("Entité inconnue : utilisez %(allowed)s.")
        % {"allowed": ", ".join(HEADERS_BY_ENTITY)}
    )


# --------------------------------------------------------------------------- #
# Écritures (toujours atomiques)
# --------------------------------------------------------------------------- #
def _create_users(rows, entity: str) -> int:
    created = 0
    for row in rows:
        user = User.objects.create(
            username=row["MATRICULE"],
            first_name=row["PRENOM"],
            last_name=row["NOM"],
            email=row["EMAIL"],
        )
        # Mot de passe aléatoire non communiqué : jamais de secret prévisible.
        set_random_password(user)

        faculty_id = row["faculty_id"] or None
        department_id = row["department_id"] or None
        if entity == "students":
            Student.objects.create(
                user=user,
                registration_number=row["MATRICULE"],
                faculty_id=faculty_id,
                department_id=department_id,
            )
        else:
            Teacher.objects.create(user=user, faculty_id=faculty_id, department_id=department_id)
        created += 1
    return created


@transaction.atomic
def _create_enrollments(rows) -> dict:
    created = skipped = 0
    for row in rows:
        _created, _obj = Enrollment.objects.get_or_create(
            student_id=row["student_id"],
            course_id=row["course_id"],
            defaults={"academic_year_id": row["academic_year_id"]},
        )
        if _created:
            created += 1
        else:
            skipped += 1
    return {"created": created, "skipped": skipped}


@transaction.atomic
def _create_assignments(rows) -> dict:
    created = skipped = 0
    for row in rows:
        course = Course.objects.select_related("department").get(pk=row["course_id"])
        _created = CourseAssignment.objects.get_or_create(
            course_id=row["course_id"],
            teacher_id=row["teacher_id"],
            academic_year_id=row["academic_year_id"],
            defaults={"department": course.department, "is_active": row["active"]},
        )[0]
        if _created:
            created += 1
        else:
            skipped += 1
    return {"created": created, "skipped": skipped}


# --------------------------------------------------------------------------- #
# API publique : import direct (legacy), aperçu, commit
# --------------------------------------------------------------------------- #
@transaction.atomic
def import_users(
    source,
    entity: Entity = "students",
    strict_placement: bool = True,
    university=None,
) -> int:
    """
    Import direct (validate-then-create) conservé pour l'API historique.

    :return: nombre d'enregistrements créés.
    :raises ImportValidationError: en-tête manquant, lignes invalides ou doublons
        (rollback total — aucun enregistrement partiel).
    """
    target = resolve_university(university)
    if entity not in ("students", "teachers"):
        raise ImportValidationError(
            _("Entité inconnue : utilisez 'students' ou 'teachers'.")
        )

    name = getattr(source, "name", "") or ""
    headers, records = _load_rows(source, name)
    _check_headers("students" if entity == "students" else "teachers", headers)
    if not records:
        raise ImportValidationError(_("Le fichier ne contient aucune ligne de données."))

    rows, errors, duplicates = _validate(
        entity, records, strict_placement=strict_placement, university=target
    )
    if errors or duplicates:
        raise ImportValidationError(
            _("%(count)s ligne(s) invalide(s). Aucun enregistrement n'a été importé.")
            % {"count": len(errors) + len(duplicates)},
            errors=errors,
            duplicates=duplicates,
        )
    return _create_users(rows, entity)


def preview_import(
    source,
    entity: str,
    *,
    strict_placement: bool = True,
    university=None,
) -> dict:
    """
    Phase 1 — validation sans écriture.

    :return: rapport {token, entity, university, total, valid, errors, duplicates,
            sample}; `token` permet de confirmer l'écriture (`commit_import`).
    """
    if entity not in HEADERS_BY_ENTITY:
        raise ImportValidationError(
            _("Entité inconnue : utilisez %(allowed)s.")
            % {"allowed": ", ".join(HEADERS_BY_ENTITY)}
        )
    target = resolve_university(university)

    name = getattr(source, "name", "") or ""
    headers, records = _load_rows(source, name)
    _check_headers(entity, headers)
    if not records:
        raise ImportValidationError(_("Le fichier ne contient aucune ligne de données."))

    rows, errors, duplicates = _validate(
        entity, records, strict_placement=strict_placement, university=target
    )

    token = secrets.token_urlsafe(24)
    payload = {
        "entity": entity,
        "university_id": str(target.pk),
        "created_by": None,
        "rows": rows,
    }
    cache.set(f"import-preview:{token}", payload, PREVIEW_TTL_SECONDS)

    return {
        "token": token,
        "entity": entity,
        "entity_label": ENTITY_LABELS.get(entity, entity),
        "university": str(target.pk),
        "university_name": target.name,
        "total": len(records),
        "valid": len(rows),
        "errors": errors,
        "duplicates": duplicates,
        "sample": [
            {key: value for key, value in row.items() if not key.endswith("_id")}
            for row in rows[:PREVIEW_SAMPLE_SIZE]
        ],
    }


@transaction.atomic
def commit_import(
    token: str,
    *,
    university=None,
    actor=None,
    skip_duplicates: bool = False,
) -> dict:
    """
    Phase 2 — confirmation d'écriture, après re-validation des données stockées.

    :param token: jeton d'aperçu (durée de vie limitée).
    :param skip_duplicates: ignorer les lignes en doublon (les autres erreurs
        restent bloquantes).
    :raises ImportValidationError: aperçu expiré, université différente, ou
        données redevenues invalides (doublons apparus entre-temps).
    """
    payload = cache.get(f"import-preview:{token}")
    if not payload:
        raise ImportValidationError(
            _("Aperçu expiré : rechargez le fichier et refaites la validation.")
        )

    target = resolve_university(university or payload.get("university_id"))
    if payload.get("university_id") != str(target.pk):
        raise ImportValidationError(
            _("L'aperçu a été généré pour une autre université : refaites la validation.")
        )

    entity = payload["entity"]
    rows = payload.get("rows") or []
    if not rows:
        raise ImportValidationError(_("Aucune ligne valide à importer."))

    # Rejeu de la validation : l'état de la base a pu changer depuis l'aperçu.
    fresh_rows, errors, duplicates = _revalidate_rows(
        entity, rows, university=target
    )
    if errors or (duplicates and not skip_duplicates):
        raise ImportValidationError(
            _("%(count)s ligne(s) invalide(s). Aucun enregistrement n'a été importé.")
            % {"count": len(errors) + len(duplicates)},
            errors=errors,
            duplicates=duplicates,
        )

    if not fresh_rows:
        raise ImportValidationError(_("Aucune ligne valide à importer."))

    if entity in ("students", "teachers"):
        created = _create_users(fresh_rows, entity)
        result = {"created": created, "skipped": 0}
    elif entity == "enrollments":
        result = _create_enrollments(fresh_rows)
    else:
        result = _create_assignments(fresh_rows)

    cache.delete(f"import-preview:{token}")
    return {
        "entity": entity,
        "entity_label": ENTITY_LABELS.get(entity, entity),
        "university": str(target.pk),
        "imported": result["created"],
        "skipped": result.get("skipped", 0),
        "actor": getattr(actor, "username", None),
    }


def _revalidate_rows(entity: str, rows: list[dict], *, university: University):
    """
    Revalide les lignes stockées par l'aperçu contre l'état **courant** de la
    base (doublons apparus, objets supprimés, affectation active prise…).
    Les UUID résolus à l'aperçu sont réutilisés (aucune re-résolution par nom).
    """
    if entity in ("students", "teachers"):
        return _revalidate_users(rows, university=university)
    if entity == "enrollments":
        return _revalidate_enrollments(rows, university=university)
    return _revalidate_assignments(rows, university=university)


def _revalidate_users(rows: list[dict], *, university: University):
    existing = set(
        User.objects.filter(
            username__in=[row["MATRICULE"] for row in rows]
        ).values_list("username", flat=True)
    )
    faculties = {
        str(faculty.pk): faculty
        for faculty in Faculty.objects.filter(university=university)
    }
    departments = {
        str(department.pk): department
        for department in Department.objects.filter(faculty__university=university)
    }

    valid, errors, duplicates = [], [], []
    seen: set[str] = set()
    for row in rows:
        matricule = row["MATRICULE"]
        if matricule in existing or matricule in seen:
            duplicates.append(
                {"line": row.get("line"), "identifier": matricule,
                 "reason": str(_("Matricule déjà existant (doublon apparu après l'aperçu)."))}
            )
            continue

        messages: list[str] = []
        faculty = faculties.get(row.get("faculty_id", ""))
        if row.get("faculty_id") and faculty is None:
            messages.append(str(_("Faculté supprimée ou hors université : refaites l'aperçu.")))
        department = departments.get(row.get("department_id", ""))
        if row.get("department_id") and department is None:
            messages.append(str(_("Département supprimé ou hors université : refaites l'aperçu.")))
        if department and faculty and department.faculty_id != faculty.pk:
            messages.append(str(_("Département rattaché à une autre faculté.")))
        if not _is_valid_email(row["EMAIL"]):
            messages.append(str(_("EMAIL invalide : %(email)s.")) % {"email": row["EMAIL"]})

        if messages:
            errors.append(
                {"line": row.get("line"), "message": " ".join(messages)}
            )
            continue

        seen.add(matricule)
        existing.add(matricule)
        valid.append(row)
    return valid, errors, duplicates


def _revalidate_enrollments(rows: list[dict], *, university: University):
    students = {
        str(student.pk): student
        for student in Student.objects.filter(faculty__university=university).select_related(
            "faculty"
        )
    }
    courses = {
        str(course.pk): course
        for course in Course.objects.filter(
            department__faculty__university=university
        ).select_related("department__faculty")
    }
    years = {str(year.pk) for year in AcademicYear.objects.all()}
    existing = {
        (str(student_id), str(course_id))
        for student_id, course_id in Enrollment.objects.values_list(
            "student_id", "course_id"
        )
    }

    valid, errors, duplicates = [], [], []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        student = students.get(row.get("student_id", ""))
        course = courses.get(row.get("course_id", ""))
        year_id = row.get("academic_year_id", "")
        messages: list[str] = []
        if student is None:
            messages.append(str(_("Étudiant introuvable ou hors université : refaites l'aperçu.")))
        if course is None:
            messages.append(str(_("Cours introuvable ou hors université : refaites l'aperçu.")))
        if year_id not in years:
            messages.append(str(_("Année académique introuvable : refaites l'aperçu.")))

        key = (row.get("student_id", ""), row.get("course_id", ""))
        if student and course and (key in existing or key in seen):
            duplicates.append(
                {"line": row.get("line"),
                 "identifier": f"{student.registration_number} → {course.code}",
                 "reason": str(_("Inscription déjà existante."))}
            )
            continue
        if student and course and student.faculty_id and course.department.faculty_id != student.faculty_id:
            messages.append(str(_("Le cours appartient à une autre faculté que l'étudiant.")))

        if messages:
            errors.append({"line": row.get("line"), "message": " ".join(messages)})
            continue

        seen.add(key)
        existing.add(key)
        valid.append(row)
    return valid, errors, duplicates


def _revalidate_assignments(rows: list[dict], *, university: University):
    teachers = {
        str(teacher.pk): teacher
        for teacher in Teacher.objects.filter(faculty__university=university).select_related(
            "department"
        )
    }
    courses = {
        str(course.pk): course
        for course in Course.objects.filter(
            department__faculty__university=university
        ).select_related("department")
    }
    years = {str(year.pk) for year in AcademicYear.objects.all()}
    active_by_key = {
        (str(row["course_id"]), str(row["academic_year_id"])): str(row["teacher_id"])
        for row in CourseAssignment.objects.filter(
            is_active=True, course__department__faculty__university=university
        ).values("course_id", "academic_year_id", "teacher_id")
    }

    valid, errors, duplicates = [], [], []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        teacher = teachers.get(row.get("teacher_id", ""))
        course = courses.get(row.get("course_id", ""))
        year_id = row.get("academic_year_id", "")
        active = bool(row.get("active", True))
        messages: list[str] = []
        if teacher is None:
            messages.append(str(_("Enseignant introuvable ou hors université : refaites l'aperçu.")))
        if course is None:
            messages.append(str(_("Cours introuvable ou hors université : refaites l'aperçu.")))
        if year_id not in years:
            messages.append(str(_("Année académique introuvable : refaites l'aperçu.")))
        if teacher and course and teacher.department_id != course.department_id:
            messages.append(str(_("L'enseignant n'appartient pas au département du cours.")))

        key = (row.get("course_id", ""), year_id)
        if course and key in seen:
            duplicates.append(
                {"line": row.get("line"),
                 "identifier": f"{row.get('MATRICULE', '')} → {course.code}",
                 "reason": str(_("Affectation en doublon dans le fichier."))}
            )
            continue
        existing_teacher = active_by_key.get(key)
        if teacher and course and existing_teacher and active:
            if existing_teacher == str(teacher.pk):
                duplicates.append(
                    {"line": row.get("line"),
                     "identifier": f"{row.get('MATRICULE', '')} → {course.code}",
                     "reason": str(_("Affectation active déjà existante."))}
                )
                continue
            messages.append(
                str(_("Un responsable actif existe déjà pour ce cours et cette année."))
            )

        if messages:
            errors.append({"line": row.get("line"), "message": " ".join(messages)})
            continue

        seen.add(key)
        valid.append(row)
    return valid, errors, duplicates
