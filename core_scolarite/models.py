"""
Modèles académiques — core_scolarite (ARCHITECTURE §6.2).

Moteur du formulaire dynamique : l'admin configure ProblemType +
AttachmentConfig sans toucher au code.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
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
    program = models.ForeignKey(
        "accounts.Program",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="courses",
        verbose_name=_("programme"),
    )
    is_active = models.BooleanField(_("actif"), default=True)
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


class Enrollment(UUIDModel):
    """
    Inscription réelle d'un étudiant à une UE (référence de filtrage du
    formulaire dynamique). En l'absence d'inscriptions, le repli s'effectue
    sur le département de l'étudiant (mode MVP).
    """

    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name=_("student"),
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name=_("course"),
    )
    academic_year = models.CharField(
        _("academic year"),
        max_length=9,
        blank=True,
        help_text=_("ex. 2025-2026"),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("enrollment")
        verbose_name_plural = _("enrollments")
        ordering = ["course__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="enrollment_student_course_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["student"], name="enroll_student_idx"),
        ]

    def __str__(self):
        return f"{self.student.registration_number} → {self.course.code}"


class ProblemType(UUIDModel):
    """
    Type de problème = règle de comportement du formulaire dynamique.
    requires_course=True force la sélection d'une UE côté étudiant.

    `university` isole la configuration par université (NULL = modèle
    global rétrocompatible) ; `is_active` active/désactive le type côté
    étudiant sans jamais le supprimer (historique des requêtes préservé).
    """

    university = models.ForeignKey(
        "accounts.University",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="problem_types",
        verbose_name=_("université"),
    )
    name = models.CharField(_("name"), max_length=100)
    description = models.TextField(
        _("description"), blank=True, help_text=_("Instructions shown to the student.")
    )
    requires_course = models.BooleanField(
        _("requires course"),
        default=True,
        help_text=_("Check when this problem concerns a specific course."),
    )
    is_active = models.BooleanField(_("actif"), default=True)
    position = models.PositiveIntegerField(_("ordre"), default=0)
    updated_at = models.DateTimeField(_("mis à jour le"), auto_now=True)

    class Meta:
        verbose_name = _("problem type")
        verbose_name_plural = _("problem types")
        ordering = ["position", "name"]
        constraints = [
            # Unicité par université (multi-tenants)…
            models.UniqueConstraint(
                fields=["university", "name"],
                name="problem_type_university_name_uniq",
            ),
            # …et globale pour les types sans université (index partiel).
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(university__isnull=True),
                name="problem_type_global_name_uniq",
            ),
        ]

    @classmethod
    def visible_to(cls, university=None):
        """
        Types publiables pour une université : ceux de l'université + les
        modèles globaux, uniquement actifs (isolation + activation serveur).
        """
        queryset = cls.objects.filter(is_active=True)
        if university is None:
            return queryset.filter(university__isnull=True)
        return queryset.filter(
            models.Q(university__isnull=True) | models.Q(university=university)
        )

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
    allowed_types = models.CharField(
        _("types de fichiers"),
        max_length=120,
        default="pdf,png,jpg,jpeg,webp",
        help_text=_("Extensions acceptées, séparées par des virgules."),
    )
    max_size_mb = models.PositiveSmallIntegerField(
        _("taille maximale (Mo)"),
        default=8,
        help_text=_("Ne peut dépasser la limite serveur."),
    )

    class Meta:
        verbose_name = _("attachment config")
        verbose_name_plural = _("attachment configs")
        ordering = ["problem_type", "label"]

    def clean(self):
        super().clean()
        from django.conf import settings  # import local : évite toute boucle d'imports

        extensions = [
            ext.strip().lower().lstrip(".")
            for ext in (self.allowed_types or "").split(",")
            if ext.strip()
        ]
        if not extensions:
            raise ValidationError(
                {"allowed_types": _("Indiquez au moins une extension.")}
            )
        unauthorized = [
            ext for ext in extensions if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS
        ]
        if unauthorized:
            raise ValidationError(
                {
                    "allowed_types": _(
                        "Extension(s) non autorisée(s) par le serveur : %(exts)s."
                    )
                    % {"exts": ", ".join(unauthorized)}
                }
            )
        self.allowed_types = ",".join(extensions)
        server_cap = max(1, settings.MAX_UPLOAD_SIZE // (1024 * 1024))
        if not 1 <= int(self.max_size_mb or 0) <= server_cap:
            raise ValidationError(
                {
                    "max_size_mb": _(
                        "La taille maximale doit être comprise entre 1 et %(cap)s Mo."
                    )
                    % {"cap": server_cap}
                }
            )

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [
            ext.strip().lower()
            for ext in (self.allowed_types or "").split(",")
            if ext.strip()
        ]

    def __str__(self):
        return f"{self.label} ({self.problem_type.name})"


class Subject(UUIDModel):
    """Matière (contenu pédagogique) rattachée à un cours."""

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="subjects",
        verbose_name=_("cours"),
    )
    code = models.CharField(_("code"), max_length=20, blank=True)
    name = models.CharField(_("intitulé"), max_length=150)
    hours = models.PositiveSmallIntegerField(
        _("volume horaire (h)"), default=0
    )
    position = models.PositiveIntegerField(_("ordre"), default=0)

    class Meta:
        verbose_name = _("matière")
        verbose_name_plural = _("matières")
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"], name="subject_course_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["course", "position"], name="subject_course_idx"),
        ]

    @property
    def university(self):
        return self.course.department.faculty.university if self.course_id else None

    def __str__(self):
        return f"{self.name} ({self.course.code})"


class CourseAssignment(UUIDModel):
    """
    Affectation d'un enseignant à un cours pour une année académique.
    C'est **l'affectation active** qui désigne le responsable automatique
    d'une requête déposée sur ce cours (cohérence validée côté serveur).
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name=_("cours"),
    )
    teacher = models.ForeignKey(
        "accounts.Teacher",
        on_delete=models.CASCADE,
        related_name="course_assignments",
        verbose_name=_("enseignant"),
    )
    academic_year = models.ForeignKey(
        "accounts.AcademicYear",
        on_delete=models.PROTECT,
        related_name="course_assignments",
        verbose_name=_("année académique"),
    )
    department = models.ForeignKey(
        "accounts.Department",
        on_delete=models.PROTECT,
        related_name="course_assignments",
        verbose_name=_("département"),
    )
    is_active = models.BooleanField(_("actif"), default=True)
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)

    class Meta:
        verbose_name = _("affectation enseignant")
        verbose_name_plural = _("affectations enseignants")
        ordering = ["-academic_year__code", "course__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "teacher", "academic_year"],
                name="course_assignment_uniq",
            ),
            # Un seul responsable actif par cours et par année (cohérence).
            models.UniqueConstraint(
                fields=["course", "academic_year"],
                condition=models.Q(is_active=True),
                name="course_assignment_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["academic_year", "is_active"],
                name="ca_year_active_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.course_id:
            return
        course = self.course
        if self.department_id and self.department_id != course.department_id:
            raise ValidationError(
                {"department": _("Le département doit être celui du cours.")}
            )
        if self.teacher_id and self.teacher.department_id != course.department_id:
            raise ValidationError(
                {"teacher": _("L'enseignant n'appartient pas au département du cours.")}
            )
    @property
    def university(self):
        return self.course.department.faculty.university if self.course_id else None

    @classmethod
    def responsible(cls, course, academic_year=None):
        """
        Enseignant responsable actif d'un cours (année fournie ou courante).
        Retourne None quand aucune affectation valide n'existe.
        """
        queryset = cls.objects.filter(course=course, is_active=True)
        if academic_year is not None:
            queryset = queryset.filter(academic_year=academic_year)
        else:
            from accounts.models import AcademicYear

            current = AcademicYear.current()
            if current is not None:
                queryset = queryset.filter(academic_year=current)
        assignment = queryset.select_related("teacher").first()
        return assignment.teacher if assignment else None

    def __str__(self):
        return (
            f"{self.course.code} — {self.teacher.full_name} [{self.academic_year.code}]"
        )


class ProblemTypeRequiredCourse(UUIDModel):
    """Cours exigé (ou suggéré) par un type de requête donné."""

    problem_type = models.ForeignKey(
        ProblemType,
        on_delete=models.CASCADE,
        related_name="required_courses",
        verbose_name=_("type de requête"),
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="required_for_types",
        verbose_name=_("cours"),
    )
    is_required = models.BooleanField(_("obligatoire"), default=True)

    class Meta:
        verbose_name = _("cours requis")
        verbose_name_plural = _("cours requis")
        ordering = ["course__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem_type", "course"],
                name="ptr_course_uniq",
            ),
        ]

    @property
    def university(self):
        return getattr(self.problem_type, "university", None)

    def __str__(self):
        flag = _("obligatoire") if self.is_required else _("optionnel")
        return f"{self.problem_type.name} → {self.course.code} ({flag})"


class FormField(UUIDModel):
    """
    Champ paramétrable ajouté à un type de requête (formulaire dynamique).
    `key` est stable : il sert de clé dans le snapshot conservé à la soumission.
    """

    class FieldType(models.TextChoices):
        TEXT = "text", _("Texte court")
        TEXTAREA = "textarea", _("Texte long")
        NUMBER = "number", _("Nombre")
        DATE = "date", _("Date")
        SELECT = "select", _("Liste de choix")
        CHECKBOX = "checkbox", _("Case à cocher")

    problem_type = models.ForeignKey(
        ProblemType,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("type de requête"),
    )
    key = models.SlugField(
        _("clé technique"),
        max_length=50,
        help_text=_("Identifiant stable (lettres minuscules, chiffres, tirets)."),
    )
    label = models.CharField(_("libellé"), max_length=150)
    field_type = models.CharField(
        _("type"), max_length=10, choices=FieldType.choices, default=FieldType.TEXT
    )
    is_required = models.BooleanField(_("obligatoire"), default=False)
    help_text = models.CharField(
        _("texte d'aide"), max_length=200, blank=True
    )
    choices_list = models.TextField(
        _("choix"),
        blank=True,
        help_text=_("Un choix par ligne (type « Liste de choix » uniquement)."),
    )
    position = models.PositiveIntegerField(_("ordre"), default=0)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("champ de formulaire")
        verbose_name_plural = _("champs de formulaire")
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem_type", "key"], name="form_field_pt_key_uniq"
            ),
        ]

    def clean(self):
        super().clean()
        self.key = (self.key or "").strip().lower()
        if self.key and not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.key):
            raise ValidationError(
                {
                    "key": _(
                        "Clé invalide : lettres minuscules, chiffres, tirets uniquement."
                    )
                }
            )
        if self.field_type == self.FieldType.SELECT:
            values = self.choices_values
            if len(values) < 2:
                raise ValidationError(
                    {"choices_list": _("Indiquez au moins deux choix (un par ligne).")}
                )

    @property
    def choices_values(self) -> list[str]:
        return [
            line.strip()
            for line in (self.choices_list or "").splitlines()
            if line.strip()
        ]

    @property
    def university(self):
        return getattr(self.problem_type, "university", None)

    def __str__(self):
        return f"{self.label} ({self.problem_type.name})"


class ConditionalRule(UUIDModel):
    """
    Règle conditionnelle : selon la valeur d'un champ source, on masque,
    on affiche ou on rend obligatoire un champ cible.
    """

    class Operator(models.TextChoices):
        EQUALS = "equals", _("est égal à")
        NOT_EQUALS = "not_equals", _("n'est pas égal à")
        CONTAINS = "contains", _("contient")
        IS_SET = "is_set", _("est renseigné")

    class Action(models.TextChoices):
        SHOW = "show", _("Afficher")
        HIDE = "hide", _("Masquer")
        REQUIRE = "require", _("Rendre obligatoire")

    field = models.ForeignKey(
        FormField,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("champ cible"),
    )
    depends_on = models.ForeignKey(
        FormField,
        on_delete=models.CASCADE,
        related_name="dependent_rules",
        verbose_name=_("champ source"),
    )
    operator = models.CharField(
        _("opérateur"), max_length=12, choices=Operator.choices, default=Operator.EQUALS
    )
    value = models.CharField(_("valeur"), max_length=200, blank=True)
    action = models.CharField(
        _("effet"), max_length=10, choices=Action.choices, default=Action.SHOW
    )

    class Meta:
        verbose_name = _("règle conditionnelle")
        verbose_name_plural = _("règles conditionnelles")
        ordering = ["field__position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["field", "depends_on", "operator", "value", "action"],
                name="conditional_rule_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.field_id or not self.depends_on_id:
            return
        if self.field_id == self.depends_on_id:
            raise ValidationError(
                {"depends_on": _("Une règle ne peut dépendre d'elle-même.")}
            )
        if self.field.problem_type_id != self.depends_on.problem_type_id:
            raise ValidationError(
                {"depends_on": _("Les deux champs doivent appartenir au même type.")}
            )
        if self.operator == self.Operator.IS_SET:
            self.value = ""
        elif not (self.value or "").strip():
            raise ValidationError({"value": _("La valeur de comparaison est requise.")})

    def matches(self, raw_value) -> bool:
        """Évalue la règle pour une valeur brute fournie par l'étudiant."""
        value = str(raw_value if raw_value is not None else "").strip()
        target = (self.value or "").strip()
        if self.operator == self.Operator.IS_SET:
            return value != ""
        if self.operator == self.Operator.EQUALS:
            return value.casefold() == target.casefold()
        if self.operator == self.Operator.NOT_EQUALS:
            return value.casefold() != target.casefold()
        if self.operator == self.Operator.CONTAINS:
            return target.casefold() in value.casefold()
        return False

    @property
    def university(self):
        return getattr(self.field, "university", None)

    def __str__(self):
        return f"{self.field.key} ← {self.depends_on.key} ({self.get_operator_display()})"


class AuditLog(UUIDModel):
    """
    Journal d'audit **immuable** des opérations administratives :
    chaque création/modification/import/export est tracé avec son acteur.
    """

    class Action(models.TextChoices):
        CREATE = "create", _("Création")
        UPDATE = "update", _("Modification")
        DELETE = "delete", _("Suppression")
        IMPORT = "import", _("Import")
        EXPORT = "export", _("Export")
        PUBLISH = "publish", _("Publication")
        TRANSITION = "transition", _("Changement de statut")
        CREDENTIALS = "credentials", _("Émission d'accès")

    actor = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("acteur"),
    )
    action = models.CharField(_("action"), max_length=12, choices=Action.choices)
    model_label = models.CharField(
        _("entité"), max_length=100, help_text=_("app_label.ModelName")
    )
    object_pk = models.CharField(_("clé"), max_length=64, blank=True)
    object_repr = models.CharField(_("représentation"), max_length=255, blank=True)
    changes = models.JSONField(_("changements"), default=dict, blank=True)
    university = models.ForeignKey(
        "accounts.University",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name=_("université"),
    )
    ip = models.GenericIPAddressField(_("adresse IP"), null=True, blank=True)
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)

    class Meta:
        verbose_name = _("entrée d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="audit_created_idx"),
            models.Index(
                fields=["university", "created_at"], name="audit_uni_created_idx"
            ),
            models.Index(fields=["model_label"], name="audit_model_idx"),
        ]

    def save(self, *args, **kwargs):
        # Journal immuable : pas de réécriture d'audit a posteriori.
        if not self._state.adding and not getattr(self, "_allow_audit_mutation", False):
            raise ValidationError(_("Le journal d'audit est immuable : modification refusée."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not getattr(self, "_allow_audit_mutation", False):
            raise ValidationError(_("Le journal d'audit est immuable : suppression refusée."))
        return super().delete(*args, **kwargs)

    @classmethod
    def record(
        cls,
        *,
        actor=None,
        action: str,
        obj=None,
        changes: dict | None = None,
        university=None,
        ip=None,
        model_label: str = "",
        object_repr: str = "",
        object_pk: str = "",
    ) -> "AuditLog":
        """Construit (sans lever) une entrée d'audit normalisée."""
        if obj is not None:
            model_label = model_label or f"{obj._meta.app_label}.{obj._meta.model_name}"
            object_pk = object_pk or str(obj.pk)
            object_repr = object_repr or str(obj)[:255]
        return cls.objects.create(
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            action=action,
            model_label=model_label,
            object_pk=object_pk,
            object_repr=object_repr,
            changes=changes or {},
            university=university,
            ip=ip,
        )

    def __str__(self):
        who = self.actor.username if self.actor_id else _("Système")
        return f"{self.get_action_display()} — {self.model_label} {self.object_pk[:8]} ({who})"


class SlaPolicy(UUIDModel):
    """
    Règle configurable : identification des requêtes **en retard** et des
    dossiers **bloqués** (délais + statuts pris en compte).
    """

    university = models.ForeignKey(
        "accounts.University",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sla_policies",
        verbose_name=_("université"),
    )
    name = models.CharField(_("nom"), max_length=150)
    max_days = models.PositiveIntegerField(
        _("délai de traitement (jours)"),
        default=5,
        help_text=_("Requête considérée en retard au-delà de ce délai."),
    )
    blocked_after_days = models.PositiveIntegerField(
        _("délai de blocage (jours)"),
        default=10,
        help_text=_("Dossier considéré comme bloqué au-delà de ce délai."),
    )
    statuses = models.CharField(
        _("statuts suivis"),
        max_length=80,
        default="SENT,RECEIVED,PROCESSING,MORE_INFO",
        help_text=_("Liste de statuts séparés par des virgules."),
    )
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("règle de délai")
        verbose_name_plural = _("règles de délai")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["university", "name"], name="sla_policy_uni_name_uniq"
            ),
        ]

    def clean(self):
        super().clean()
        from tickets.models import Ticket  # import local : évite le cycle d'imports

        values = self.statuses_list
        if not values:
            raise ValidationError({"statuses": _("Indiquez au moins un statut.")})
        invalid = [v for v in values if v not in Ticket.Status.values]
        if invalid:
            raise ValidationError(
                {"statuses": _("Statut(s) inconnu(s) : %(vals)s.") % {"vals": ", ".join(invalid)}}
            )
        if self.blocked_after_days < self.max_days:
            raise ValidationError(
                {
                    "blocked_after_days": _(
                        "Le délai de blocage doit être supérieur ou égal au délai de traitement."
                    )
                }
            )

    @property
    def statuses_list(self) -> list[str]:
        return [s.strip().upper() for s in (self.statuses or "").split(",") if s.strip()]

    @property
    def university_scope(self):
        return self.university_id

    def age_days(self, ticket, now) -> float:
        reference = ticket.updated_at or ticket.created_at
        if reference is None:
            return 0.0
        if timezone.is_naive(reference):
            reference = timezone.make_aware(reference)
        return (now - reference).total_seconds() / 86400

    def is_in_scope(self, ticket) -> bool:
        return ticket.status in self.statuses_list

    def is_overdue(self, ticket, now=None) -> bool:
        now = now or timezone.now()
        return self.is_in_scope(ticket) and self.age_days(ticket, now) > self.max_days

    def is_blocked(self, ticket, now=None) -> bool:
        now = now or timezone.now()
        return self.is_in_scope(ticket) and self.age_days(ticket, now) > self.blocked_after_days

    def __str__(self):
        scope = self.university.name if self.university_id else _("Toutes universités")
        return f"{self.name} ({scope})"


class ReminderPolicy(UUIDModel):
    """Relance configurable : notification envoyée à un rôle après un délai."""

    class TargetRole(models.TextChoices):
        STUDENT = "student", _("Étudiant")
        TEACHER = "teacher", _("Enseignant")

    university = models.ForeignKey(
        "accounts.University",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reminder_policies",
        verbose_name=_("université"),
    )
    name = models.CharField(_("nom"), max_length=150)
    delay_days = models.PositiveIntegerField(_("délai avant relance (jours)"), default=3)
    target_role = models.CharField(
        _("destinataire"), max_length=10, choices=TargetRole.choices, default=TargetRole.TEACHER
    )
    title = models.CharField(
        _("titre"), max_length=150, default=_("Relance : requête en attente")
    )
    message = models.TextField(_("message"), blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("relance")
        verbose_name_plural = _("relances")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["university", "name"],
                name="reminder_policy_uni_name_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if not (self.title or "").strip():
            raise ValidationError({"title": _("Le titre est obligatoire.")})

    def __str__(self):
        return f"{self.name} (J+{self.delay_days}, {self.get_target_role_display()})"


class InstitutionSyncConfig(UUIDModel):
    """
    Préparation d'une synchronisation avec le système universitaire officiel
    (API ou annuaire institutionnel). **Aucun secret en base** : seule la
    *nom* de la variable d'environnement contenant les identifiants est stockée.
    """

    class Mode(models.TextChoices):
        DISABLED = "disabled", _("Désactivée")
        API = "api", _("API REST")
        LDAP = "ldap", _("Annuaire (LDAP)")

    class AuthType(models.TextChoices):
        NONE = "none", _("Aucune")
        TOKEN = "token", _("Jeton")
        BASIC = "basic", _("Basique")
        OAUTH2 = "oauth2", _("OAuth2")

    university = models.OneToOneField(
        "accounts.University",
        on_delete=models.PROTECT,
        related_name="sync_config",
        verbose_name=_("université"),
    )
    mode = models.CharField(
        _("mode"), max_length=10, choices=Mode.choices, default=Mode.DISABLED
    )
    endpoint = models.URLField(_("point d'accès"), blank=True)
    auth_type = models.CharField(
        _("authentification"),
        max_length=10,
        choices=AuthType.choices,
        default=AuthType.TOKEN,
    )
    credential_env = models.CharField(
        _("variable d'environnement des identifiants"),
        max_length=100,
        blank=True,
        help_text=_("Nom de la variable (ex. UNIV_SSYNC_TOKEN) — jamais sa valeur."),
    )
    external_id_field = models.CharField(
        _("champ d'identifiant externe"), max_length=50, default="matricule"
    )
    last_sync_at = models.DateTimeField(_("dernière synchro"), null=True, blank=True)
    last_status = models.CharField(_("dernier statut"), max_length=20, blank=True)
    last_message = models.TextField(_("dernier message"), blank=True)

    class Meta:
        verbose_name = _("synchronisation institutionnelle")
        verbose_name_plural = _("synchronisations institutionnelles")

    @property
    def is_enabled(self) -> bool:
        return self.mode != self.Mode.DISABLED

    @property
    def secret_lookup_env(self) -> str:
        return (self.credential_env or "").strip().upper()

    def __str__(self):
        return f"{self.university.name} — {self.get_mode_display()}"
