"""
Modèles du workflow — tickets (ARCHITECTURE §6.3).

Ticket : cycle de vie SENT → RECEIVED → PROCESSING → {RESOLVED, REJECTED},
clé UUID, index composites (student,status) / (teacher,status) et contrainte
garantissant qu'un rejet porte toujours un motif non vide.
TicketAttachment : pièce jointe rattachée à une règle AttachmentConfig.
TicketStatusHistory : journal horodaté de chaque changement de statut/décision.
"""

import uuid
from datetime import date

from django.core.exceptions import ValidationError
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
        MORE_INFO = "MORE_INFO", _("Infos demandées")
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
    academic_year = models.CharField(
        _("academic year"),
        max_length=9,
        blank=True,
        help_text=_("Session académique concernée, ex. 2025-2026."),
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=Status.choices,
        default=Status.SENT,
    )
    rejection_reason = models.TextField(_("rejection reason"), null=True, blank=True)
    # Demande d'informations complémentaires (enseignant → étudiant).
    complementary_info_request = models.TextField(
        _("complementary info request"), blank=True
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    # Horodatages d'analytique (§6.3) : sans eux, impossible de calculer le
    # temps de réponse moyen par faculté (updated_at change à chaque mutation).
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    # Snapshot de la configuration du formulaire au moment de la soumission :
    # une modification ultérieure du type (champs, pièces, règles) ne déforme
    # jamais l'historique des requêtes existantes.
    config_snapshot = models.JSONField(
        _("configuration à la soumission"), default=dict, blank=True
    )
    # Réponses aux champs dynamiques du formulaire (validées côté serveur).
    form_data = models.JSONField(
        _("réponses au formulaire"), default=dict, blank=True
    )

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


class TicketComment(UUIDModel):
    """
    Commentaire horodaté sur un ticket (réponse de l'étudiant à une demande
    d'informations complémentaires, ou message de l'enseignant).
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("ticket"),
    )
    author = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("author"),
    )
    body = models.TextField(_("body"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("ticket comment")
        verbose_name_plural = _("ticket comments")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket", "created_at"], name="tc_ticket_created_idx"),
        ]

    @property
    def author_label(self) -> str:
        if self.author is None:
            return str(_("Inconnu"))
        return self.author.get_full_name() or self.author.username

    def __str__(self):
        return f"Commentaire {self.ticket.short_id} — {self.created_at:%d/%m/%Y %H:%M}"


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

    @property
    def file_extension(self) -> str:
        """Extension lisible du fichier stocké (le nom sert jamais de chemin client)."""
        name = self.file.name or ""
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    @property
    def is_image(self) -> bool:
        """True pour les pièces consultables en image (aperçu inline protégé)."""
        return self.file_extension in {"png", "jpg", "jpeg", "webp"}

    def __str__(self):
        return f"{self.config.label} — {self.ticket.short_id}"


class TicketStatusHistory(UUIDModel):
    """
    Entrée immuable d'historique : chaque création et chaque transition de
    statut laisse une trace horodatée avec son acteur et son motif éventuel.
    """

    class ActorRole(models.TextChoices):
        STUDENT = "student", _("Étudiant")
        TEACHER = "teacher", _("Enseignant")
        SYSTEM = "system", _("Système")

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name=_("ticket"),
    )
    from_status = models.CharField(
        _("from status"),
        max_length=15,
        choices=Ticket.Status.choices,
        null=True,
        blank=True,
    )
    to_status = models.CharField(
        _("to status"), max_length=15, choices=Ticket.Status.choices
    )
    actor = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("actor"),
    )
    actor_role = models.CharField(
        _("actor role"),
        max_length=10,
        choices=ActorRole.choices,
        default=ActorRole.SYSTEM,
    )
    note = models.TextField(_("note"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("ticket status history")
        verbose_name_plural = _("ticket status histories")
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["ticket", "created_at"], name="tsh_ticket_created_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        """
        Journal immuable pour les utilisateurs ordinaires (§6/§9) : une entrée
        créée ne peut plus être modifiée. Le flag `_allow_history_mutation`
        est réservé aux opérations système/administratives rares et explicites.
        """
        if not self._state.adding and not getattr(
            self, "_allow_history_mutation", False
        ):
            raise ValidationError(
                _("L'historique des statuts est immuable : modification refusée.")
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not getattr(self, "_allow_history_mutation", False):
            raise ValidationError(
                _("L'historique des statuts est immuable : suppression refusée.")
            )
        return super().delete(*args, **kwargs)

    @property
    def from_status_label(self) -> str:
        return dict(Ticket.Status.choices).get(self.from_status, "—") if self.from_status else "—"

    @property
    def to_status_label(self) -> str:
        return dict(Ticket.Status.choices).get(self.to_status, self.to_status)

    @property
    def actor_label(self) -> str:
        if self.actor is None:
            return str(_("Système"))
        name = self.actor.get_full_name() or self.actor.username
        return f"{name}"

    def __str__(self):
        return f"{self.ticket.short_id}: {self.from_status or '—'} → {self.to_status}"
