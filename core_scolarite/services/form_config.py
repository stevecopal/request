"""
Formulaires dynamiques — validation de cohérence, publication et snapshot.

Le SuperAdmin configure un type de requête (champs, règles conditionnelles,
pièces jointes, cours requis). Deux garanties serveur :

1. `coherence_errors()` contrôle la configuration **avant publication** :
   clés dupliquées, listes de choix incomplètes, règles orphelines, cours
   rattachés à une autre université, etc.
2. `build_snapshot()` fige la configuration au moment de la soumission :
   une modification ultérieure du type ne déforme jamais l'historique des
   requêtes existantes (`Ticket.config_snapshot`).

`validate_dynamic_fields()` rejette côté serveur tout champ obligatoire
manquant ou toute règle conditionnelle non respectée (jamais de confiance
dans le client).
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core_scolarite.models import ConditionalRule, FormField, ProblemType

__all__ = [
    "ConfigurationError",
    "coherence_errors",
    "build_snapshot",
    "validate_dynamic_fields",
]


class ConfigurationError(Exception):
    """Configuration incohérente : la publication est refusée."""

    def __init__(self, errors):
        self.errors = [str(error) for error in errors]
        super().__init__(" ".join(self.errors))


def coherence_errors(problem_type: ProblemType) -> list[str]:
    """Contrôle de cohérence d'un type de requête (vide = publiable)."""
    errors: list[str] = []

    fields = list(problem_type.fields.all().order_by("position", "id"))
    seen_keys: set[str] = set()
    for field in fields:
        if field.key in seen_keys:
            errors.append(
                _("Clé technique dupliquée : %(key)s.") % {"key": field.key}
            )
        seen_keys.add(field.key)
        if (
            field.field_type == FormField.FieldType.SELECT
            and len(field.choices_values) < 2
        ):
            errors.append(
                _("Champ « %(label)s » : liste de choix incomplète (2 minimum).")
                % {"label": field.label}
            )

    field_ids = {field.id for field in fields}
    rules = ConditionalRule.objects.filter(field__problem_type=problem_type).select_related(
        "field", "depends_on"
    )
    for rule in rules:
        if rule.depends_on_id not in field_ids:
            errors.append(
                _("Règle conditionnelle orpheline sur « %(key)s ».")
                % {"key": rule.field.key}
            )
        if not rule.value and rule.operator != ConditionalRule.Operator.IS_SET:
            errors.append(
                _("Règle conditionnelle sans valeur de comparaison sur « %(key)s ».")
                % {"key": rule.field.key}
            )

    for attachment in problem_type.required_attachments.all():
        if not attachment.allowed_extensions_list:
            errors.append(
                _("Pièce jointe « %(label)s » : aucune extension autorisée.")
                % {"label": attachment.label}
            )

    university_id = problem_type.university_id
    if university_id:
        foreign = [
            link.course.code
            for link in problem_type.required_courses.select_related(
                "course__department__faculty"
            )
            if link.course.department.faculty.university_id != university_id
        ]
        if foreign:
            errors.append(
                _("Cours rattachés à une autre université : %(codes)s.")
                % {"codes": ", ".join(foreign)}
            )

    if problem_type.requires_course and not problem_type.required_courses.exists():
        errors.append(
            _("Ce type exige un cours : rattachez au moins un cours requis.")
        )

    return errors


def publish(problem_type: ProblemType) -> None:
    """Publie un type de requête (active) si la configuration est cohérente."""
    errors = coherence_errors(problem_type)
    if errors:
        raise ConfigurationError(errors)
    problem_type.is_active = True
    problem_type.save(update_fields=["is_active", "updated_at"])


def build_snapshot(problem_type: ProblemType) -> dict:
    """Fige la configuration courante d'un type de requête (JSON immuable)."""
    return {
        "taken_at": timezone.now().isoformat(),
        "config_version": (
            problem_type.updated_at.isoformat() if problem_type.updated_at else None
        ),
        "problem_type": {
            "id": str(problem_type.id),
            "name": problem_type.name,
            "requires_course": problem_type.requires_course,
            "description": problem_type.description,
        },
        "fields": [
            {
                "key": field.key,
                "label": field.label,
                "type": field.field_type,
                "required": field.is_required,
                "help_text": field.help_text,
                "choices": field.choices_values,
            }
            for field in problem_type.fields.all().order_by("position", "id")
        ],
        "attachments": [
            {
                "id": str(attachment.id),
                "label": attachment.label,
                "required": attachment.is_required,
                "types": attachment.allowed_extensions_list,
                "max_size_mb": attachment.max_size_mb,
            }
            for attachment in problem_type.required_attachments.order_by("label")
        ],
        "rules": [
            {
                "field": rule.field.key,
                "depends_on": rule.depends_on.key,
                "operator": rule.operator,
                "value": rule.value,
                "action": rule.action,
            }
            for rule in ConditionalRule.objects.filter(
                field__problem_type=problem_type
            ).select_related("field", "depends_on")
        ],
        "courses": [
            {
                "code": link.course.code,
                "name": link.course.name,
                "required": link.is_required,
            }
            for link in problem_type.required_courses.select_related("course").order_by(
                "course__code"
            )
        ],
    }


def validate_dynamic_fields(problem_type: ProblemType, values: dict | None) -> dict:
    """
    Valide et normalise les réponses aux champs dynamiques.

    * les champs **inactifs** ou appartenant à un autre type sont ignorés ;
    * les champs obligatoires doivent être renseignés (sauf si masqués par une
      règle conditionnelle) ;
    * les règles conditionnelles (afficher/masquer/obligatoire) sont
      réévaluées côté serveur sur les valeurs soumises.

    :raises ConfigurationError: champs invalides, messages par clé technique.
    """
    values = values or {}
    answers: dict[str, object] = {}
    field_errors: dict[str, list[str]] = {}

    fields = list(
        problem_type.fields.filter(is_active=True).order_by("position", "id")
    )
    by_key = {field.key: field for field in fields}

    def _raw(field) -> str:
        return str(values.get(field.key, "") or "").strip()

    # 1. Normalisation par type (les valeurs hors liste de choix sont rejetées).
    for field in fields:
        raw = _raw(field)
        if field.field_type == FormField.FieldType.CHECKBOX:
            answers[field.key] = raw.lower() in ("1", "true", "on", "yes", "oui")
            continue
        if not raw:
            answers[field.key] = ""
            continue
        if field.field_type == FormField.FieldType.NUMBER:
            try:
                answers[field.key] = float(raw) if "." in raw else int(raw)
            except ValueError:
                field_errors.setdefault(field.key, []).append(
                    _("Valeur numérique invalide.")
                )
                answers[field.key] = ""
        elif field.field_type == FormField.FieldType.SELECT:
            if raw not in field.choices_values:
                field_errors.setdefault(field.key, []).append(
                    _("Choix hors liste autorisée.")
                )
                answers[field.key] = ""
            else:
                answers[field.key] = raw
        else:
            answers[field.key] = raw

    # 2. Règles conditionnelles : visibilité / obligation.
    def _is_visible(field) -> bool:
        visible = True
        for rule in field.conditions.select_related("depends_on"):
            source = by_key.get(rule.depends_on.key)
            if source is None:
                continue
            source_value = answers.get(source.key, "")
            if rule.matches(source_value):
                if rule.action == ConditionalRule.Action.SHOW:
                    visible = True
                elif rule.action == ConditionalRule.Action.HIDE:
                    visible = False
        return visible

    def _is_required(field) -> bool:
        if field.is_required:
            return True
        for rule in field.conditions.select_related("depends_on"):
            source = by_key.get(rule.depends_on.key)
            if source is None:
                continue
            if rule.matches(answers.get(source.key, "")) and rule.action in (
                ConditionalRule.Action.REQUIRE,
                ConditionalRule.Action.SHOW,
            ):
                # « Afficher » ne rend pas obligatoire ; seul REQUIRE le fait.
                if rule.action == ConditionalRule.Action.REQUIRE:
                    return True
        return False

    for field in fields:
        if not _is_visible(field):
            continue
        value = answers.get(field.key, "")
        empty = value in ("", None, False)
        if _is_required(field) and empty:
            field_errors.setdefault(field.key, []).append(_("Champ obligatoire."))

    if field_errors:
        raise ConfigurationError(
            [
                f"{by_key[key].label} : {' '.join(messages)}"
                for key, messages in field_errors.items()
                if key in by_key
            ]
        )

    return answers
