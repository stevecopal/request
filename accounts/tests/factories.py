"""Fabrique de test partagée : université racine pour les jeux de tests."""

from accounts.models import University


def make_university(name="Université Test"):
    """Crée (ou récupère) une université de test."""
    return University.objects.get_or_create(name=name)[0]
