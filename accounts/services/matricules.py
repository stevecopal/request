"""
Matricules officiels — génération sans collision et validation stricte.

Format étudiant (brief UnivReq) :

    CM-UDS-22SCI0001
    │    │   │ │  └── numéro d'ordre (4 chiffres, généré, sans collision)
    │    │   │ └───── code de la faculté (liste officielle configurée, ex. SCI)
    │    │   └─────── année d'inscription (2 chiffres, ex. 22 pour 2022)
    │    └─────────── code de l'université (ex. UDS — Université de Dschang)
    └──────────────── code pays (ex. CM — Cameroun)

Format enseignant : identique, mais le bloc « faculté » est remplacé par le
segment enseignant configuré (`TEACHER_MATRICULE_SEGMENT`, défaut « ENS »),
ex. `CM-UDS-22ENS0001`.

Règles :
  * pays / université proviennent du profil `University` (configuration) ;
  * code de faculté provient de `Faculty.code` (liste officielle configurée
    dans la console C2) ;
  * l'année provient de l'année académique courante (à défaut, l'année en cours) ;
  * le numéro d'ordre est calculé sans collision (incrément du maximum existant)
    et la création est reprise sur `IntegrityError` par l'appelant.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext as _

ENTITY_STUDENTS = "students"
ENTITY_TEACHERS = "teachers"

TEACHER_SEGMENT_DEFAULT = "ENS"
SEQUENCE_WIDTH = 4

# Fenêtre raisonnable d'année d'inscription (détection des coquilles).
YEAR_WINDOW_YEARS = 20

MATRICULE_RE = re.compile(
    r"^(?P<country>[A-Z]{2})-(?P<university>[A-Z0-9]{2,10})-"
    r"(?P<year>\d{2})(?P<segment>[A-Z0-9]{2,6})(?P<sequence>\d{4})$"
)


def teacher_segment() -> str:
    """Segment enseignant configurable (défini séparément du segment faculté)."""
    value = getattr(settings, "TEACHER_MATRICULE_SEGMENT", TEACHER_SEGMENT_DEFAULT)
    return (value or TEACHER_SEGMENT_DEFAULT).strip().upper()


def registration_year(university=None) -> int:
    """Année d'inscription : année de l'année académique courante (sinon N-1 an)."""
    from accounts.models import AcademicYear

    year = AcademicYear.current()
    if year is not None and year.start_date:
        return year.start_date.year
    return timezone.now().year


def segment_for(faculty, entity: str) -> str:
    """Bloc segment attendu : code faculté (étudiant) ou segment enseignant."""
    if entity == ENTITY_TEACHERS:
        return teacher_segment()
    code = getattr(faculty, "code", "") or ""
    return code.strip().upper()


def matricule_prefix(faculty, entity: str, year: int | None = None) -> str:
    """Préfixe `CM-UDS-22SCI` du matricule à générer (sans le numéro d'ordre)."""
    university = faculty.university
    if year is None:
        year = registration_year(university)
    segment = segment_for(faculty, entity)
    if not segment:
        raise ValueError(
            _(
                "Code de faculté non configuré : renseignez-le dans la console "
                "avant de générer un matricule étudiant."
            )
        )
    return (
        f"{university.country_code.strip().upper()}-"
        f"{university.code.strip().upper()}-{year % 100:02d}{segment}"
    )


def _next_sequence(prefix: str) -> int:
    """Numéro d'ordre suivant : max existant + 1 (aucune collision possible)."""
    highest = 0
    for username in User.objects.filter(username__startswith=prefix).values_list(
        "username", flat=True
    ):
        suffix = username[len(prefix):]
        if suffix.isdigit() and len(suffix) == SEQUENCE_WIDTH:
            highest = max(highest, int(suffix))
    return highest + 1


def build(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:0{SEQUENCE_WIDTH}d}"


def generate(faculty, entity: str, year: int | None = None) -> str:
    """Génère le prochain matricule libre pour (faculté, type de compte)."""
    prefix = matricule_prefix(faculty, entity, year=year)
    return build(prefix, _next_sequence(prefix))


def parse(value: str):
    """Décompose un matricule, ou renvoie None s'il ne respecte pas le format."""
    match = MATRICULE_RE.match((value or "").strip().upper())
    return match.groupdict() if match else None


def validate(
    value: str,
    *,
    entity: str,
    university=None,
    faculty=None,
) -> str:
    """
    Valide un matricule fourni (saisie manuelle ou import) et le renvoie
    normalisé en majuscules.

    Contrôles :
      1. format officiel `PAYS_UNIV_AASSEGNNNN` ;
      2. codes pays / université conformes à l'université cible ;
      3. segment conforme : code de la faculté (étudiant) ou segment
         enseignant configuré (enseignant) ;
      4. cohérence faculté ↔ matricule lorsque la faculté est connue ;
      5. année d'inscription plausible (pas dans le futur, 20 ans maximum).

    :raises ValueError: message utilisateur prêt à afficher.
    """
    normalized = (value or "").strip().upper()
    parts = parse(normalized)
    if parts is None:
        raise ValueError(
            _(
                "MATRICULE invalide : format attendu CM-UDS-22SCI0001 "
                "(pays-université-annéeCodeFaculté-numéro)."
            )
        )

    target = university or getattr(faculty, "university", None)
    if target is not None:
        if parts["country"] != target.country_code.strip().upper():
            raise ValueError(
                _(
                    "MATRICULE invalide : code pays « %(got)s » attendu « %(expected)s »."
                )
                % {"got": parts["country"], "expected": target.country_code.upper()}
            )
        if parts["university"] != target.code.strip().upper():
            raise ValueError(
                _(
                    "MATRICULE invalide : code université « %(got)s » attendu "
                    "« %(expected)s »."
                )
                % {"got": parts["university"], "expected": target.code.upper()}
            )

    expected_segment = segment_for(faculty, entity)
    if not expected_segment:
        raise ValueError(
            _(
                "Code de faculté non configuré : impossible de vérifier le "
                "matricule (console C2 → Facultés → code)."
            )
        )
    if parts["segment"] != expected_segment:
        if entity == ENTITY_TEACHERS:
            raise ValueError(
                _(
                    "MATRICULE invalide : le segment enseignant attendu est "
                    "« %(expected)s » (ex. CM-UDS-22%(expected)s0001)."
                )
                % {"expected": expected_segment}
            )
        raise ValueError(
            _(
                "MATRICULE incohérent : le code faculté « %(got)s » ne "
                "correspond pas à « %(expected)s » (%(faculty)s)."
            )
            % {
                "got": parts["segment"],
                "expected": expected_segment,
                "faculty": getattr(faculty, "name", _("faculté")),
            }
        )

    current_year = registration_year(target)
    year_value = 2000 + int(parts["year"])
    if year_value > current_year or year_value < current_year - YEAR_WINDOW_YEARS:
        raise ValueError(
            _(
                "MATRICULE invalide : année d'inscription %(year)s hors de la "
                "fenêtre attendue (%(from)s–%(to)s)."
            )
            % {
                "year": year_value,
                "from": current_year - YEAR_WINDOW_YEARS,
                "to": current_year,
            }
        )

    return normalized


__all__ = [
    "ENTITY_STUDENTS",
    "ENTITY_TEACHERS",
    "SEQUENCE_WIDTH",
    "TEACHER_SEGMENT_DEFAULT",
    "build",
    "generate",
    "matricule_prefix",
    "parse",
    "registration_year",
    "segment_for",
    "teacher_segment",
    "validate",
]
