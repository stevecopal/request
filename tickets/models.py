"""
Modèles du workflow — tickets (ARCHITECTURE §6.3).

Ticket : cycle de vie SENT → RECEIVED → PROCESSING → {RESOLVED, REJECTED},
clé UUID, index composites (student,status) / (teacher,status) et contrainte
garantissant qu'un rejet porte toujours un motif non vide.
TicketAttachment : pièce jointe rattachée à une règle AttachmentConfig.
"""

import uuid
from datetime import date

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel


def attachment_upload_to(instance, filename):
    """
    Chemin de stockage des pièces jointes — nom réécrit en UUID.

    Aucun nom de fichier client n'atteint le système de fichiers (§9.4) :
    évite le path traversal et les collisions.
    """
    today = date.today()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"tickets/attachments/{today:%Y/%m/%d}/{uuid.uuid4().hex}.{extension}"


class Ticket(UUIDModel):
    """Requête académique soumise par un étudiant à un enseignant."""

    class Status(models.TextChoices):
        SENT = "SENT", _("Envoyé")
        RECEIVED = "RECEIVED", _("Reçu")
        PROCESSING = "PROCESSING", _("En cours")
        RESOLVED = "RESOLVED", _("Résolu")
        REJECTED = "REJECTED", _("Rejeté")

    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.CASCADE,
        related_name="tickets",
        verbose_name=_("student"),
    )
    teacher = models.ForeignKey(
        "accounts.Teacher",
        on_delete=models.PROTECT,
        related_name="tickets",
        verbose_name=_("teacher"),
    )
    course = models.ForeignKey(
        "core_scolarite.Course",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
        verbose_name=_("course"),
    )
    problem_type = models.ForeignKey(
        "core_scolarite.ProblemType",
        on_delete=models.PROTECT,
        related_name="tickets",
        verbose_name=_("problem type"),
    )
    description = models.TextField(_("description"))
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=Status.choices,
        default=Status.SENT,
    )
    rejection_reason = models.TextField(_("rejection reason"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    # Horodatages d'analytique (§6.3) : sans eux, impossible de calculer le
    # temps de réponse moyen par faculté (updated_at change à chaque mutation).
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)

    class Meta:
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        ordering = ["-created_at"]
        indexes = [
            # Tableaux de bord personnels < 5 ms (§6.3, §12)
            models.Index(fields=["student", "status"], name="ticket_student_status_idx"),
            models.Index(fields=["teacher", "status"], name="ticket_teacher_status_idx"),
            # Liste admin / analytique chronologique
            models.Index(fields=["status", "created_at"], name="ticket_status_created_idx"),
        ]
        constraints = [
            # Un ticket REJECTED a nécessairement un motif non vide (§6.4)
            models.CheckConstraint(
                condition=~models.Q(status="REJECTED")
                | (~models.Q(rejection_reason__isnull=True) & ~models.Q(rejection_reason="")),
                name="ticket_rejection_reason_required",
            ),
        ]

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    @property
    def is_open(self) -> bool:
        """True tant que le ticket n'a pas atteint un état terminal."""
        return self.status not in (self.Status.RESOLVED, self.Status.REJECTED)

    def __str__(self):
        return f"{self.problem_type} — {self.student.full_name} [{self.get_status_display()}]"


class TicketAttachment(UUIDModel):
    """Pièce jointe d'un ticket, rattachée à la règle qui l'a exigée."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("ticket"),
    )
    config = models.ForeignKey(
        "core_scolarite.AttachmentConfig",
        on_delete=models.PROTECT,
        verbose_name=_("attachment config"),
    )
    file = models.FileField(
        _("file"), upload_to=attachment_upload_to, max_length=255
    )

    class Meta:
        verbose_name = _("ticket attachment")
        verbose_name_plural = _("ticket attachments")
        ordering = ["config__label"]

    def __str__(self):
        return f"{self.config.label} — {self.ticket.short_id}"
