"""
Formulaires core_scolarite — import (upload), création manuelle, règles admin
(Phase 10) et formulaires de la console super-admin (C1–C6).
"""

from django import forms
from django.contrib.auth.models import Permission, User
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tickets.models import Ticket

from accounts.models import (
    AcademicYear,
    Department,
    Faculty,
    Program,
    Student,
    Teacher,
    University,
)

from .models import (
    AttachmentConfig,
    ConditionalRule,
    Course,
    CourseAssignment,
    DecisionRule,
    FormField,
    ProblemType,
    ReminderPolicy,
    Service,
    ServiceAssignment,
    SlaPolicy,
    TechnicalEvent,
)

ENTITY_CHOICES = [("students", _("Étudiants")), ("teachers", _("Enseignants"))]


class ImportForm(forms.Form):
    """Formulaire d'upload ETL (validé côté service pour les erreurs ligne à ligne)."""

    entity = forms.ChoiceField(label=_("Type de comptes"), choices=ENTITY_CHOICES)
    file = forms.FileField(
        label=_("Fichier CSV/XLSX"),
        help_text=_("En-têtes requis : " + "MATRICULE, NOM, PRENOM, EMAIL, FACULTE, DEPARTEMENT"),
    )
    strict_placement = forms.BooleanField(
        label=_("Exiger faculté et département"),
        required=False,
        initial=True,
        help_text=_("Décochez pour importer des profils à compléter par l'étudiant."),
    )


class ManualAccountForm(forms.Form):
    """Création manuelle d'un compte (étudiant ou enseignant) — option A du brief."""

    entity = forms.ChoiceField(label=_("Type de compte"), choices=ENTITY_CHOICES)
    matricule = forms.CharField(label=_("Matricule"), max_length=50)
    first_name = forms.CharField(label=_("Prénom"), max_length=150)
    last_name = forms.CharField(label=_("Nom"), max_length=150)
    email = forms.EmailField(label=_("Email"))
    title = forms.ChoiceField(
        label=_("Titre"),
        choices=Teacher.TITLE_CHOICES,
        required=False,
        help_text=_("Requis pour un compte enseignant."),
    )
    faculty = forms.ModelChoiceField(
        label=_("Faculté"),
        queryset=Faculty.objects.filter(is_active=True),
        empty_label=_("Sélectionnez une faculté"),
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.none(),
        empty_label=_("Sélectionnez un département"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        faculty_id = self.data.get("faculty") or getattr(self.initial.get("faculty"), "pk", None)
        if faculty_id:
            self.fields["department"].queryset = Department.objects.filter(
                faculty_id=faculty_id, is_active=True
            )

    def clean_matricule(self):
        matricule = self.cleaned_data["matricule"].strip()
        if User.objects.filter(username=matricule).exists():
            raise forms.ValidationError(_("Ce matricule existe déjà."))
        return matricule

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("entity")
        department = cleaned.get("department")
        faculty = cleaned.get("faculty")
        if department and faculty and department.faculty_id != faculty.pk:
            raise forms.ValidationError(
                _("Le département sélectionné n'appartient pas à cette faculté.")
            )
        if entity == "teachers" and not cleaned.get("title"):
            self.add_error("title", _("Le titre est requis pour un enseignant."))
        return cleaned


class AttachmentConfigForm(forms.ModelForm):
    """Édition d'une règle de pièce jointe (Phase 10)."""

    class Meta:
        model = AttachmentConfig
        fields = ("problem_type", "label", "is_required")


class ProblemTypeForm(forms.ModelForm):
    """Édition d'un type de problème (Phase 10)."""

    class Meta:
        model = ProblemType
        fields = ("name", "description", "requires_course")


# --------------------------------------------------------------------------- #
# Console super-admin (C1–C6) — formulaires de la barre latérale et des modales
# --------------------------------------------------------------------------- #


class ConsoleFormMixin:
    """Applique les classes du design system (`.field`) à tous les widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault(
                    "class",
                    "h-4 w-4 rounded border-slate-300 text-navy-800 focus:ring-navy-600",
                )
            else:
                widget.attrs.setdefault("class", "field")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", "3")
            if isinstance(widget, forms.SelectMultiple):
                widget.attrs.setdefault("size", "8")


# --- C2 : organisation ------------------------------------------------------ #


class FacultyForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = Faculty
        fields = ("name",)

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university


class DepartmentForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ("faculty", "name")

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        faculties = Faculty.objects.filter(is_active=True)
        if university is not None:
            faculties = faculties.filter(university=university)
        self.fields["faculty"].queryset = faculties.order_by("name")


class ProgramForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = Program
        fields = ("department", "code", "name", "level")

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        departments = Department.objects.filter(
            is_active=True, faculty__is_active=True
        )
        if university is not None:
            departments = departments.filter(faculty__university=university)
        self.fields["department"].queryset = departments.select_related("faculty").order_by(
            "faculty__name", "name"
        )


class ServiceForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ("name", "description", "contact_email")

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university


class ServiceMemberForm(ConsoleFormMixin, forms.Form):
    """Affectation d'un enseignant ou d'un agent à un service."""

    user = forms.ModelChoiceField(
        label=_("Utilisateur"),
        queryset=User.objects.none(),
        empty_label=_("Sélectionnez une personne"),
    )
    role = forms.ChoiceField(label=_("Rôle"), choices=ServiceAssignment.Role.choices)

    def __init__(self, *args, university=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Enseignants, agents (sans profil étudiant) et administrateurs.
        candidates = User.objects.filter(
            Q(is_superuser=True)
            | Q(is_staff=True)
            | Q(teacher_profile__isnull=False)
            | (Q(student_profile__isnull=True) & Q(teacher_profile__isnull=True))
        ).filter(is_active=True)
        if university is not None:
            candidates = candidates.filter(
                Q(is_superuser=True)
                | Q(is_staff=True)
                | Q(teacher_profile__faculty__university=university)
                | (Q(student_profile__isnull=True) & Q(teacher_profile__isnull=True))
            )
        self.fields["user"].queryset = candidates.distinct().order_by("username")
        if instance is not None and instance.user_id:
            self.fields["user"].queryset = (
                self.fields["user"].queryset | User.objects.filter(pk=instance.user_id)
            ).distinct()


class CourseAssignmentForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = CourseAssignment
        fields = ("course", "teacher", "academic_year", "department", "is_active")

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        courses = Course.objects.filter(is_active=True).select_related("department")
        teachers = Teacher.objects.select_related("faculty", "department", "user")
        departments = Department.objects.filter(is_active=True).select_related("faculty")
        if university is not None:
            courses = courses.filter(department__faculty__university=university)
            teachers = teachers.filter(faculty__university=university)
            departments = departments.filter(faculty__university=university)
        self.fields["course"].queryset = courses.order_by("code")
        self.fields["teacher"].queryset = teachers.order_by("user__last_name")
        self.fields["department"].queryset = departments.order_by("faculty__name", "name")
        self.fields["academic_year"].queryset = AcademicYear.objects.order_by("-code")
        # Cohérence départ/cours : on pré-remplit le département depuis le cours.
        if not self.is_bound and self.instance.course_id:
            self.fields["department"].initial = self.instance.course.department_id

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        department = cleaned.get("department")
        if course and department and department.pk != course.department_id:
            self.add_error(
                "department", _("Le département doit être celui du cours.")
            )
        return cleaned


# --- C4 : workflow ---------------------------------------------------------- #


class ProblemTypeConsoleForm(ConsoleFormMixin, forms.ModelForm):
    """
    Catégorie de requête (C4). L'université n'est **pas** un champ éditable :
    la console crée dans son périmètre de travail (`instance.university`,
    appliqué côté serveur) et conserve l'affectation existante à l'édition.
    """

    class Meta:
        model = ProblemType
        fields = (
            "name",
            "description",
            "service",
            "requires_course",
            "position",
            "is_active",
        )

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        services = Service.objects.filter(is_active=True)
        if university is not None:
            services = services.filter(university=university)
        self.fields["service"].queryset = services.order_by("name")
        self.fields["service"].required = False
        self.fields["description"].widget.attrs.setdefault("rows", "3")

    def clean(self):
        cleaned = super().clean()
        service = cleaned.get("service")
        university = self.university or getattr(self.instance, "university", None)
        if (
            service is not None
            and university is not None
            and service.university_id != university.pk
        ):
            self.add_error("service", _("Le service appartient à une autre université."))
        return cleaned


class FormFieldConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = FormField
        fields = (
            "key",
            "label",
            "field_type",
            "is_required",
            "help_text",
            "choices_list",
            "position",
            "is_active",
        )

    def __init__(self, *args, problem_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.problem_type = problem_type
        self.fields["choices_list"].widget.attrs.setdefault("rows", "3")
        if self.instance.pk is None and problem_type is not None:
            self.instance.problem_type = problem_type


class AttachmentConfigConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = AttachmentConfig
        fields = ("label", "is_required", "allowed_types", "max_size_mb")

    def __init__(self, *args, problem_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.problem_type = problem_type
        if self.instance.pk is None and problem_type is not None:
            self.instance.problem_type = problem_type


class ConditionalRuleConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = ConditionalRule
        fields = ("field", "depends_on", "operator", "value", "action")

    def __init__(self, *args, problem_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.problem_type = problem_type
        fields = FormField.objects.filter(problem_type=problem_type).order_by(
            "position", "id"
        )
        self.fields["field"].queryset = fields
        self.fields["depends_on"].queryset = fields
        self.fields["field"].empty_label = _("Sélectionnez un champ")
        self.fields["depends_on"].empty_label = _("Sélectionnez un champ")
        if self.instance.pk:
            self.fields["field"].queryset = fields.exclude(pk=self.instance.field_id)
            self.fields["depends_on"].queryset = fields.exclude(pk=self.instance.depends_on_id)


class RequiredCourseConsoleForm(ConsoleFormMixin, forms.Form):
    course = forms.ModelChoiceField(
        label=_("Cours"),
        queryset=Course.objects.none(),
        empty_label=_("Sélectionnez un cours"),
    )
    is_required = forms.BooleanField(
        label=_("Obligatoire"), required=False, initial=True
    )

    def __init__(self, *args, problem_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(is_active=True).select_related("department")
        university = getattr(problem_type, "university", None)
        if university is not None:
            courses = courses.filter(department__faculty__university=university)
        if problem_type is not None:
            linked = list(problem_type.required_courses.values_list("course_id", flat=True))
            courses = courses.exclude(pk__in=linked)
        self.fields["course"].queryset = courses.order_by("code")


class SlaPolicyConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = SlaPolicy
        fields = (
            "name",
            "problem_type",
            "max_days",
            "blocked_after_days",
            "statuses",
            "is_active",
        )

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        types = ProblemType.objects.all()
        if university is not None:
            types = types.filter(
                Q(university=university) | Q(university__isnull=True)
            )
        self.fields["problem_type"].queryset = types.order_by("name")
        self.fields["problem_type"].required = False
        self.fields["problem_type"].empty_label = _("Toutes les requêtes")


class ReminderPolicyConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = ReminderPolicy
        fields = ("name", "delay_days", "target_role", "title", "message", "is_active")

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        self.fields["message"].widget.attrs.setdefault("rows", "3")


class DecisionRuleConsoleForm(ConsoleFormMixin, forms.ModelForm):
    class Meta:
        model = DecisionRule
        fields = ("action", "scope", "position", "is_active")

    def __init__(self, *args, problem_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.problem_type = problem_type
        if self.instance.pk is None and problem_type is not None:
            self.instance.problem_type = problem_type


# --- C1 : comptes ----------------------------------------------------------- #

ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_NONE = "none"

ROLE_CHOICES = [
    (ROLE_ADMIN, _("Administrateur")),
    (ROLE_TEACHER, _("Enseignant")),
    (ROLE_STUDENT, _("Étudiant")),
    (ROLE_NONE, _("Aucun rôle métier")),
]


class AdminUserForm(ConsoleFormMixin, forms.Form):
    """
    Édition d'un compte depuis la console (C1) : identité, statut, rôle,
    rattachement universitaire et permissions Django.

    Les changements de rôle sont appliqués dans `save()` (transaction) :
    création/suppression de profil, drapeaux `is_superuser`/`is_staff` et
    permissions explicites. Les profils porteurs de requêtes ne sont jamais
    supprimés (refusé en validation).
    """

    first_name = forms.CharField(label=_("Prénom"), max_length=150)
    last_name = forms.CharField(label=_("Nom"), max_length=150)
    email = forms.EmailField(label=_("Email"))
    is_active = forms.BooleanField(
        label=_("Compte actif"), required=False, initial=True
    )
    role = forms.ChoiceField(label=_("Rôle"), choices=ROLE_CHOICES)
    faculty = forms.ModelChoiceField(
        label=_("Faculté"),
        queryset=Faculty.objects.filter(is_active=True),
        required=False,
        empty_label=_("— Aucune —"),
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.none(),
        required=False,
        empty_label=_("— Aucun —"),
    )
    title = forms.ChoiceField(
        label=_("Titre (enseignant)"),
        choices=[("", "—")] + list(Teacher.TITLE_CHOICES),
        required=False,
    )
    permissions = forms.ModelMultipleChoiceField(
        label=_("Permissions"),
        queryset=Permission.objects.none(),
        required=False,
    )

    def __init__(self, *args, user=None, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_user = user
        self.university = university

        # Permissions attribuables : création / modification / consultation
        # (jamais de suppression en masse depuis la console).
        self.fields["permissions"].queryset = Permission.objects.filter(
            Q(codename__startswith="add_")
            | Q(codename__startswith="change_")
            | Q(codename__startswith="view_")
        ).select_related("content_type").order_by("content_type__app_label", "codename")

        faculty_id = None
        if self.is_bound:
            faculty_id = self.data.get("faculty") or None
        elif self.initial.get("faculty"):
            faculty_id = getattr(self.initial["faculty"], "pk", self.initial["faculty"])
        departments = Department.objects.filter(is_active=True, faculty__is_active=True)
        if university is not None:
            departments = departments.filter(faculty__university=university)
        if faculty_id:
            departments = departments.filter(faculty_id=faculty_id)
        self.fields["department"].queryset = departments.order_by("name")

        if not self.is_bound and user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.fields["is_active"].initial = user.is_active
            self.fields["role"].initial = self._current_role(user)
            self.fields["permissions"].initial = set(
                user.user_permissions.values_list("pk", flat=True)
            )
            student = getattr(user, "student_profile", None)
            teacher = getattr(user, "teacher_profile", None)
            profile = student or teacher
            if profile is not None:
                self.fields["faculty"].initial = profile.faculty_id
                self.fields["department"].initial = profile.department_id
            if teacher is not None:
                self.fields["title"].initial = teacher.title

    @staticmethod
    def _current_role(user) -> str:
        if user.is_superuser:
            return ROLE_ADMIN
        if getattr(user, "teacher_profile", None) is not None:
            return ROLE_TEACHER
        if getattr(user, "student_profile", None) is not None:
            return ROLE_STUDENT
        return ROLE_NONE

    def clean_email(self):
        email = (self.cleaned_data["email"] or "").strip()
        if not email:
            raise forms.ValidationError(_("L'email est obligatoire."))
        return email

    def clean(self):
        cleaned = super().clean()
        user = self.target_user
        role = cleaned.get("role")
        faculty = cleaned.get("faculty")
        department = cleaned.get("department")
        title = cleaned.get("title")
        is_active = cleaned.get("is_active", True)

        if user is not None:
            if role != ROLE_ADMIN and user.is_superuser and user == getattr(
                self, "actor", None
            ):
                raise forms.ValidationError(
                    _("Vous ne pouvez pas retirer vos propres droits d'administrateur.")
                )
            if is_active is False and user == getattr(self, "actor", None):
                raise forms.ValidationError(
                    _("Vous ne pouvez pas désactiver votre propre compte.")
                )

        if department and faculty and department.faculty_id != faculty.pk:
            self.add_error(
                "department", _("Le département sélectionné n'appartient pas à cette faculté.")
            )

        if role == ROLE_TEACHER:
            if not faculty:
                self.add_error("faculty", _("La faculté est requise pour un enseignant."))
            if not department:
                self.add_error("department", _("Le département est requis pour un enseignant."))
            if not title:
                self.add_error("title", _("Le titre est requis pour un enseignant."))

        if user is not None and role not in (None, self._current_role(user)):
            student = getattr(user, "student_profile", None)
            teacher = getattr(user, "teacher_profile", None)
            if role == ROLE_TEACHER and student is not None and student.tickets.exists():
                self.add_error(
                    "role",
                    _("Ce compte possède des requêtes étudiantes : créez un compte enseignant dédié."),
                )
            if role == ROLE_STUDENT and teacher is not None and teacher.tickets.exists():
                self.add_error(
                    "role",
                    _("Ce compte traite des requêtes : conversion impossible, créez un compte dédié."),
                )
            if role == ROLE_NONE and (student is not None or teacher is not None):
                self.add_error(
                    "role",
                    _("Ce compte possède un profil métier : retirez-le via un autre rôle."),
                )
        return cleaned

    def save(self) -> dict:
        """Applique identité, rôle, rattachement et permissions. Retourne le diff."""
        from core_scolarite.services.audit import diff_changes

        user = self.target_user
        cleaned = self.cleaned_data
        role = cleaned["role"]
        changes = diff_changes(
            user,
            {
                "first_name": cleaned["first_name"],
                "last_name": cleaned["last_name"],
                "email": cleaned["email"],
                "is_active": cleaned.get("is_active", True),
            },
        )

        with transaction.atomic():
            user.first_name = cleaned["first_name"]
            user.last_name = cleaned["last_name"]
            user.email = cleaned["email"]
            user.is_active = cleaned.get("is_active", True)

            student = getattr(user, "student_profile", None)
            teacher = getattr(user, "teacher_profile", None)
            current_role = self._current_role(user)

            if role == ROLE_ADMIN:
                if not user.is_superuser:
                    changes["role"] = {"from": current_role, "to": ROLE_ADMIN}
                user.is_superuser = True
                user.is_staff = True
            else:
                if user.is_superuser:
                    changes["role"] = {"from": current_role, "to": role}
                if role != ROLE_ADMIN:
                    user.is_superuser = False
                    user.is_staff = False

            if role == ROLE_STUDENT:
                if teacher is not None:
                    if teacher.tickets.exists():
                        raise forms.ValidationError(
                            _("Conversion impossible : l'enseignant traite des requêtes.")
                        )
                    teacher.delete()
                    changes["removed_profile"] = {"from": "teacher", "to": None}
                if student is None:
                    student = Student.objects.create(
                        user=user,
                        registration_number=user.username,
                        faculty=cleaned.get("faculty"),
                        department=cleaned.get("department"),
                    )
                    changes["created_profile"] = {"from": None, "to": "student"}
                else:
                    changes.update(
                        diff_changes(
                            student,
                            {
                                "faculty": cleaned.get("faculty"),
                                "department": cleaned.get("department"),
                            },
                        )
                    )
                    student.faculty = cleaned.get("faculty")
                    student.department = cleaned.get("department")
                    student.save(update_fields=["faculty", "department"])
            elif role == ROLE_TEACHER:
                if student is not None:
                    if student.tickets.exists():
                        raise forms.ValidationError(
                            _("Conversion impossible : l'étudiant possède des requêtes.")
                        )
                    student.delete()
                    changes["removed_profile"] = {"from": "student", "to": None}
                if teacher is None:
                    teacher = Teacher.objects.create(
                        user=user,
                        title=cleaned.get("title") or "MR",
                        faculty=cleaned["faculty"],
                        department=cleaned["department"],
                    )
                    changes["created_profile"] = {"from": None, "to": "teacher"}
                else:
                    changes.update(
                        diff_changes(
                            teacher,
                            {
                                "title": cleaned.get("title") or teacher.title,
                                "faculty": cleaned.get("faculty"),
                                "department": cleaned.get("department"),
                            },
                        )
                    )
                    teacher.title = cleaned.get("title") or teacher.title
                    teacher.faculty = cleaned["faculty"]
                    teacher.department = cleaned["department"]
                    teacher.save(update_fields=["title", "faculty", "department"])

            user.save()

            # Permissions explicites (remplacement complet de la liste).
            before = set(user.user_permissions.values_list("pk", flat=True))
            after = set(cleaned.get("permissions") or [])
            if before != after:
                user.user_permissions.set(after)
                changes["permissions"] = {"from": len(before), "to": len(after)}

        return changes


# --- C5 : rapports ---------------------------------------------------------- #


class ReportFilterForm(ConsoleFormMixin, forms.Form):
    """Filtres communs aux écrans/export de rapports (C5)."""

    date_from = forms.DateField(
        label=_("Du"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        label=_("Au"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    faculty = forms.ModelChoiceField(
        label=_("Faculté"),
        queryset=Faculty.objects.all(),
        required=False,
        empty_label=_("Toutes les facultés"),
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.none(),
        required=False,
        empty_label=_("Tous les départements"),
    )
    problem_type = forms.ModelChoiceField(
        label=_("Catégorie"),
        queryset=ProblemType.objects.all(),
        required=False,
        empty_label=_("Toutes les catégories"),
    )

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.university = university
        faculties = Faculty.objects.filter(is_active=True)
        departments = Department.objects.filter(is_active=True, faculty__is_active=True)
        types = ProblemType.objects.all()
        if university is not None:
            faculties = faculties.filter(university=university)
            departments = departments.filter(faculty__university=university)
            types = types.filter(Q(university=university) | Q(university__isnull=True))
        self.fields["faculty"].queryset = faculties.order_by("name")
        faculty_id = (self.data.get("faculty") or self.initial.get("faculty") or None)
        if faculty_id:
            departments = departments.filter(faculty_id=faculty_id)
        self.fields["department"].queryset = departments.order_by("name")
        self.fields["problem_type"].queryset = types.order_by("name")

    def active_filters(self) -> dict:
        """Filtres réellement actifs (serialisés pour les liens d'export)."""
        active = {}
        if not self.is_bound:
            return active
        for name in ("date_from", "date_to"):
            value = self.data.get(name) or ""
            if value:
                active[name] = value
        for name in ("faculty", "department", "problem_type"):
            value = self.data.get(name) or ""
            if value:
                active[name] = value
        return active


class AdminRequestFilterForm(ReportFilterForm):
    """
    Filtres du suivi central des requêtes (C3) : s'appuie sur les filtres de
    rapports et ajoute recherche libre, statut, retard SLA et escalade.
    """

    q = forms.CharField(
        label=_("Rechercher"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "type": "search",
                "placeholder": _("Étudiant, matricule, catégorie, cours…"),
            }
        ),
    )
    status = forms.ChoiceField(label=_("Statut"), required=False)
    overdue = forms.BooleanField(label=_("En retard (SLA)"), required=False)
    escalated = forms.BooleanField(label=_("Escaladées"), required=False)

    def __init__(self, *args, university=None, **kwargs):
        super().__init__(*args, university=university, **kwargs)
        self.fields["status"].choices = [("", _("Tous les statuts"))] + list(
            Ticket.Status.choices
        )

    def active_filters(self) -> dict:
        active = super().active_filters()
        if not self.is_bound:
            return active
        for name in ("q", "status"):
            value = self.data.get(name) or ""
            if value:
                active[name] = value
        for name in ("overdue", "escalated"):
            if self.data.get(name) in ("on", "1", "true"):
                active[name] = "on"
        return active


# --- C6 : incidents --------------------------------------------------------- #


class IncidentReportForm(ConsoleFormMixin, forms.Form):
    """Signalement manuel d'un incident technique depuis la console (C6)."""

    level = forms.ChoiceField(
        label=_("Niveau"), choices=TechnicalEvent.Level.choices, initial="WARNING"
    )
    message = forms.CharField(
        label=_("Description"),
        widget=forms.Textarea(attrs={"rows": "3", "placeholder": _("Décrivez l'incident…")}),
    )
