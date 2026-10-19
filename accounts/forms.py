"""
Formulaires accounts — connexion matricule + mot de passe, onboarding MVP.

`LoginForm` : le matricule est le `username` Django des deux rôles (§6.1).
`OnboardingForm` : cascade Faculté → Département, validée côté serveur (le
département doit appartenir à la faculté choisie). MVP : université unique —
l'université du profil est toujours dérivée de la faculté.
"""

from django import forms
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _

from .models import Department, Faculty


class LoginForm(forms.Form):
    """Authentification par matricule universitaire + mot de passe."""

    matricule = forms.CharField(
        label=_("Matricule"),
        max_length=50,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        matricule = cleaned.get("matricule")
        password = cleaned.get("password")
        if matricule and password:
            # Message d'erreur identique que le compte existe ou non (§9.2).
            self.user = authenticate(
                self.request, username=matricule.strip(), password=password
            )
            if self.user is None:
                raise forms.ValidationError(
                    _("Matricule ou mot de passe incorrect. Vérifiez vos informations.")
                )
            if not self.user.is_active:
                raise forms.ValidationError(_("Ce compte est désactivé."))
        return cleaned


class OnboardingForm(forms.Form):
    """Complétion du profil étudiant (Cas A — MVP déclaratif)."""

    faculty = forms.ModelChoiceField(
        label=_("Faculté"),
        # Seules les facultés actives sont proposées à l'onboarding (C2).
        queryset=Faculty.objects.filter(is_active=True),
        empty_label=_("Sélectionnez une faculté"),
    )
    department = forms.ModelChoiceField(
        label=_("Département"),
        queryset=Department.objects.none(),
        empty_label=_("Sélectionnez un département"),
    )

    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        faculty_id = None
        if self.data.get("faculty"):
            faculty_id = self.data.get("faculty")
        elif self.initial.get("faculty"):
            faculty_id = getattr(self.initial["faculty"], "pk", self.initial["faculty"])
        if faculty_id:
            self.fields["department"].queryset = Department.objects.filter(
                faculty_id=faculty_id, is_active=True
            )

    def clean(self):
        cleaned = super().clean()
        department = cleaned.get("department")
        faculty = cleaned.get("faculty")
        if department and faculty and department.faculty_id != faculty.pk:
            raise forms.ValidationError(
                _("Le département sélectionné n'appartient pas à cette faculté.")
            )
        return cleaned

    def save(self):
        """Applique le rattachement sur le profil passé en constructeur."""
        student = self.student
        # L'université est toujours dérivée de la faculté (jamais d'ID client).
        student.faculty = self.cleaned_data["faculty"]
        student.department = self.cleaned_data["department"]
        student.save(update_fields=["faculty", "department"])
        return student
