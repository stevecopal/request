"""
Modèles d'identité — accounts (ARCHITECTURE §6.1).

Hiérarchie : University 1─n Faculty 1─n Department ; Student/Teacher 1─1 User.
Clé primaire : UUID (core.models.UUIDModel).
`Student.faculty/department` sont nullables pour supporter le Cas A (MVP
onboarding déclaratif) ; le Cas B (LDAP/API) les renseigne à l'import.
L'université d'un profil est toujours dérivée de sa faculté (isolation
multi-universités structurelle : department → faculty → university).
"""

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel


class University(UUIDModel):
    """Université — racine de l'arbre académique (isolation multi-tenants)."""

    name = models.CharField(_("name"), max_length=150, unique=True)

    class Meta:
        verbose_name = _("university")
        verbose_name_plural = _("universities")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Faculty(UUIDModel):
    """Faculté (ex. « Faculté des Sciences ») rattachée à une université."""

    university = models.ForeignKey(
        University,
        on_delete=models.PROTECT,
        related_name="faculties",
        verbose_name=_("university"),
    )
    name = models.CharField(_("name"), max_length=150)

    class Meta:
        verbose_name = _("faculty")
        verbose_name_plural = _("Faculties")
        ordering = ["name"]
        # Un nom de faculté n'est unique que sein de son université (multi-uni)
        constraints = [
            models.UniqueConstraint(
                fields=["university", "name"], name="faculty_university_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["university", "name"], name="fac_uni_name_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.university.name})"


class Department(UUIDModel):
    """Département rattaché à une faculté (unicité stricte sur le couple)."""

    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        related_name="departments",
        verbose_name=_("faculty"),
    )
    name = models.CharField(_("name"), max_length=150)

    class Meta:
        verbose_name = _("department")
        verbose_name_plural = _("departments")
        ordering = ["name"]
        # Un département n'existe qu'une fois par faculté (§6.1)
        unique_together = ("faculty", "name")
        indexes = [
            # Index composite : parcours faculté → départements < 5 ms
            models.Index(fields=["faculty", "name"], name="dept_faculty_name_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.faculty.name})"


class Student(UUIDModel):
    """Profil étudiant lié au compte Django (MATRICULE = User.username)."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="student_profile",
        verbose_name=_("user"),
    )
    registration_number = models.CharField(
        _("registration number"), max_length=50, unique=True
    )
    # null=True → Cas A (onboarding déclaratif) ; renseigné en Cas B (LDAP)
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
        verbose_name=_("faculty"),
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="students",
        null=True,
        blank=True,
        verbose_name=_("department"),
    )

    class Meta:
        verbose_name = _("student")
        verbose_name_plural = _("students")
        ordering = ["registration_number"]
        indexes = [
            # Clé de traçabilité principale (§6.1)
            models.Index(fields=["registration_number"], name="student_matricule_idx"),
        ]

    @property
    def is_onboarded(self) -> bool:
        """False tant que faculté/département ne sont pas renseignés (Cas A)."""
        return self.faculty_id is not None and self.department_id is not None

    @property
    def university(self) -> University | None:
        """Université dérivée de la faculté (None tant que non onboardé)."""
        return self.faculty.university if self.faculty_id else None

    @property
    def full_name(self) -> str:
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return f"{self.registration_number} - {self.full_name}"


class Teacher(UUIDModel):
    """Profil enseignant lié au compte Django."""

    TITLE_CHOICES = [
        ("DR", _("Dr.")),
        ("PR", _("Pr.")),
        ("MR", _("M.")),
        ("MME", _("Mme")),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
        verbose_name=_("user"),
    )
    title = models.CharField(
        _("title"), max_length=5, choices=TITLE_CHOICES, default="MR"
    )
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.PROTECT,
        related_name="teachers",
        verbose_name=_("faculty"),
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="teachers",
        verbose_name=_("department"),
    )

    class Meta:
        verbose_name = _("teacher")
        verbose_name_plural = _("teachers")
        ordering = ["user__last_name", "user__first_name"]
        indexes = [
            # Filtrage des enseignants par département (formulaire dynamique)
            models.Index(fields=["department"], name="teacher_department_idx"),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.get_title_display()} {self.user.get_full_name() or self.user.username}"

    @property
    def university(self) -> University:
        """Université dérivée de la faculté de l'enseignant."""
        return self.faculty.university

    def __str__(self):
        return self.full_name


class PushSubscription(UUIDModel):
    """
    Abonnement Web Push d'un appareil (distinct des WebSockets : notifie
    l'utilisateur même lorsque la page est fermée). Un utilisateur peut
    posséder plusieurs abonnements (plusieurs appareils).
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name=_("user"),
    )
    endpoint = models.URLField(_("endpoint"), max_length=500, unique=True)
    p256dh = models.CharField(_("p256dh"), max_length=255)
    auth = models.CharField(_("auth"), max_length=255)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("push subscription")
        verbose_name_plural = _("push subscriptions")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Push({self.user.username}) {self.endpoint[:40]}"


class Notification(UUIDModel):
    """
    Notification centre d'un utilisateur (compteur de non-lus + accès direct
    à la requête concernée). Alimentée après commit transactionnel.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("user"),
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name=_("ticket"),
    )
    title = models.CharField(_("title"), max_length=150)
    body = models.TextField(_("body"), blank=True)
    is_read = models.BooleanField(_("is read"), default=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "is_read", "created_at"], name="notif_user_read_idx"
            ),
            models.Index(fields=["user", "created_at"], name="notif_user_created_idx"),
        ]

    @property
    def ticket_id_str(self) -> str:
        return str(self.ticket_id) if self.ticket_id else ""

    def __str__(self):
        return f"Notif({self.user.username}) {self.title[:40]}"
