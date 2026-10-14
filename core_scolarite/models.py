"""
Modèles académiques — core_scolarite (ARCHITECTURE §6.2).

Moteur du formulaire dynamique : l'admin configure ProblemType +
AttachmentConfig sans toucher au code.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel


class Course(UUIDModel):
    """Unité d'enseignement (UE) rattachée à un département."""

    code = models.CharField(_("code"), max_length=20, unique=True)  # ex. INF101
    name = models.CharField(_("name"), max_length=150)
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.CASCADE,
        related_name="courses",
        verbose_name=_("department"),
    )
    primary_instructor = models.ForeignKey(
        "accounts.Teacher",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
        verbose_name=_("primary instructor"),
    )

    class Meta:
        verbose_name = _("course")
        verbose_name_plural = _("courses")
        ordering = ["code"]
        indexes = [
            # UE du département de l'étudiant : lookup direct
            models.Index(fields=["department"], name="course_department_idx"),
        ]

    def __str__(self):
        return f"[{self.code}] {self.name}"


class ProblemType(UUIDModel):
    """
    Type de problème = règle de comportement du formulaire dynamique.
    requires_course=True force la sélection d'une UE côté étudiant.
    """

    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(
        _("description"), blank=True, help_text=_("Instructions shown to the student.")
    )
    requires_course = models.BooleanField(
        _("requires course"),
        default=True,
        help_text=_("Check when this problem concerns a specific course."),
    )

    class Meta:
        verbose_name = _("problem type")
        verbose_name_plural = _("problem types")
        ordering = ["name"]

    def __str__(self):
        return self.name


class AttachmentConfig(UUIDModel):
    """
    Règle de pièce jointe pilotée par l'admin : libellé + caractère obligatoire.
    Permet d'ajouter une exigence de fichier sans changer une ligne de code.
    """

    problem_type = models.ForeignKey(
        ProblemType,
        on_delete=models.CASCADE,
        related_name="required_attachments",
        verbose_name=_("problem type"),
    )
    label = models.CharField(
        _("label"), max_length=150, help_text=_('e.g. "Portal Screenshot"')
    )
    is_required = models.BooleanField(_("is required"), default=True)

    class Meta:
        verbose_name = _("attachment config")
        verbose_name_plural = _("attachment configs")
        ordering = ["problem_type", "label"]

    def __str__(self):
        return f"{self.label} ({self.problem_type.name})"
