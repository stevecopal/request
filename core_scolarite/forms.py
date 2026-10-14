"""
Formulaires core_scolarite — import (upload), création manuelle, règles admin (Phase 10).
"""

from django import forms
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from accounts.models import Department, Faculty, Teacher

from .models import AttachmentConfig, ProblemType

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
        label=_("Faculté"), queryset=Faculty.objects.all(), empty_label=_("Sélectionnez une faculté")
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
                faculty_id=faculty_id
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
