"""
Émission d'accès — mots de passe imprévisibles, jamais stockés en clair.

Règles du brief appliquées ici :
  * aucun mot de passe par défaut prévisible (génération `secrets` côté serveur) ;
  * le secret n'est **jamais** écrit en base en clair ni journalisé : seule la
    empreinte (hasher Django) est conservée ;
  * à la création (import, création manuelle), le mot de passe est aléatoire
    et **non communiqué** : l'accès est ensuite émis une fois par un super-admin
    (action « Émettre un accès »), affiché une seule fois et tracé à l'audit.
"""

from __future__ import annotations

import secrets
import string

from django.contrib.auth.models import User

# Alphabet sans caractères ambigus (0/O, 1/l/I) pour une communication orale sûre.
_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%&*?"
PASSWORD_LENGTH = 14

__all__ = ["generate_password", "set_random_password", "issue_one_time_password"]


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    """Mot de passe aléatoire cryptographique (au moins 1 minuscule, 1 majuscule, 1 chiffre)."""
    if length < 8:
        raise ValueError("Longueur minimale de 8 caractères.")
    while True:
        password = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


def set_random_password(user: User) -> None:
    """Fixe un mot de passe aléatoire non communiqué (création de compte)."""
    user.set_password(generate_password())
    user.save(update_fields=["password"])


def issue_one_time_password(user: User) -> str:
    """
    Régénère un mot de passe et le retourne **une seule fois** à l'appelant
    (super-admin) : à transmettre hors canal, jamais journalisé.

    L'émission est un acte d'administration explicite : le compte est donc
    activé (il démarre inactif, l'accès s'ouvrant à la première connexion).
    """
    password = generate_password()
    user.set_password(password)
    user.save(update_fields=["password"])
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
    return password
