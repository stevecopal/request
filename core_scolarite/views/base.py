"""
Vues HTML de core_scolarite (console super-admin).

Fragments injectés dans la modale maîtresse : import massif et création manuelle.
Le tableau de bord analytique vit dans `views/analytics.py`.
"""

from django.shortcuts import render

from accounts.decorators import superuser_required
from accounts.models import Faculty
from core_scolarite.forms import ManualAccountForm


@superuser_required
def admin_import_modal(request):
    """Fragment de la modale d'import massif (ETL)."""
    return render(request, "modals/admin_import.html")


@superuser_required
def admin_manual_account_modal(request):
    """Fragment de la modale de création manuelle d'un compte."""
    return render(
        request,
        "modals/admin_manual_account.html",
        {
            "form": ManualAccountForm(),
            "faculties": Faculty.objects.only("id", "name").order_by("name"),
        },
    )
