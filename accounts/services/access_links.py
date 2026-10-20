"""
Liens d'accès temporaires — première connexion et réinitialisation de mot de passe.

Procédure (brief UnivReq §3) :
  1. l'utilisateur saisit son matricule et son adresse e-mail ;
  2. le système vérifie leur correspondance avec le compte enregistré ;
  3. un lien **temporaire, sécurisé et à usage unique** est envoyé à cette
     adresse (`send_link_email`) ;
  4. l'utilisateur y définit son mot de passe et active son compte ;
  5. il se connecte ensuite avec son matricule ou son e-mail et ce mot de passe.

Sécurité :
  * le jeton brut (48 caractères aléatoires) n'est **jamais** stocké : seule
    l'empreinte SHA-256 est conservée (`AccessLink.token_hash`) ;
  * un seul lien actif par (utilisateur, objet) : l'émission invalide le
    précédent ;
  * usage unique (`used_at`) et expiration contrôlés côté serveur ;
  * en cas d'e-mail inaccessible, l'administrateur peut émettre le lien lui-même
    (procédure contrôlée, tracée à l'audit) — `issue_link(created_by=…)`.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import AccessLink

logger = logging.getLogger(__name__)

TOKEN_LENGTH = 48

# Durées de validité (configurables par variable d'environnement).
def _ttl_hours(default: int, name: str) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def activation_ttl() -> timedelta:
    return timedelta(hours=_ttl_hours(48, "ACCESS_LINK_TTL_HOURS"))


def reset_ttl() -> timedelta:
    return timedelta(hours=_ttl_hours(4, "RESET_LINK_TTL_HOURS"))


def _ttl_for(purpose: str) -> timedelta:
    return reset_ttl() if purpose == AccessLink.Purpose.RESET else activation_ttl()


def hash_token(raw_token: str) -> str:
    """Empreinte SHA-256 du jeton (seule valeur conservée en base)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_link(
    user: User,
    purpose: str,
    *,
    email: str | None = None,
    created_by: User | None = None,
) -> tuple[AccessLink, str]:
    """
    Crée un lien temporaire à usage unique et renvoie (lien, jeton brut).

    Le jeton brut n'existe que pendant cet appel et dans l'e-mail envoyé ;
    il est retourné à l'appelant (vue ou procédure admin) pour construction
    de l'URL, jamais journalisé.
    """
    destination = (email or user.email or "").strip()
    # Un seul lien actif par (utilisateur, objet) : le précédent devient obsolète.
    AccessLink.objects.filter(user=user, purpose=purpose, used_at__isnull=True).delete()

    raw_token = secrets.token_urlsafe(32)
    now = timezone.now()
    link = AccessLink.objects.create(
        user=user,
        purpose=purpose,
        token_hash=hash_token(raw_token),
        email=destination,
        expires_at=now + _ttl_for(purpose),
        created_by=created_by,
    )
    return link, raw_token


def resolve(raw_token: str, purpose: str) -> AccessLink | None:
    """Renvoie le lien correspondant au jeton (consommé ou expiré → None)."""
    if not raw_token:
        return None
    link = (
        AccessLink.objects.select_related("user", "created_by")
        .filter(token_hash=hash_token(raw_token.strip()), purpose=purpose)
        .first()
    )
    if link is None or not link.is_usable:
        return None
    return link


def consume(link: AccessLink) -> None:
    """Marque le lien comme utilisé (usage unique, contrôlé en base)."""
    AccessLink.objects.filter(pk=link.pk, used_at__isnull=True).update(
        used_at=timezone.now()
    )


def site_base() -> str:
    """
    Origine canonique du site pour les liens envoyés par e-mail.

    `SITE_URL` (variable d'environnement) prime : les e-mails sont parfois
    émis sans requête HTTP (console admin, commandes) et derrière un proxy
    l'en-tête Host peut ne pas refléter le domaine public.
    """
    return (getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")


def link_url(raw_token: str, purpose: str, request=None) -> str:
    """
    URL **absolue et cliquable** du lien (`https://mon-domaine/activation/…`).

    Priorité : `SITE_URL` (origine canonique) → requête HTTP courante →
    chemin relatif (dernier recours, dev uniquement).
    """
    route = (
        "accounts:password_reset_confirm"
        if purpose == AccessLink.Purpose.RESET
        else "accounts:activation_confirm"
    )
    path = reverse(route, args=[raw_token])
    base = site_base()
    if base:
        return f"{base}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def send_link_email(
    user: User,
    raw_token: str,
    purpose: str,
    request=None,
    *,
    created_by: User | None = None,
) -> str:
    """
    Envoie le lien à l'adresse du compte et renvoie l'URL (usage admin/dev).

    Aucun mot de passe n'est communiqué : le destinataire choisit le sien en
    suivant le lien. Le jeton brut n'est jamais journalisé.
    """
    url = link_url(raw_token, purpose, request=request)
    if purpose == AccessLink.Purpose.RESET:
        subject = _("[UnivReq] Réinitialisation de votre mot de passe")
        body = _(
            "Bonjour %(name)s,\n\n"
            "Nous avons reçu une demande de réinitialisation du mot de passe "
            "de votre compte %(matricule)s.\n\n"
            "Ouvrez ce lien pour choisir un nouveau mot de passe (valable "
            "%(hours)s heures, usage unique) :\n%(url)s\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce "
            "message : votre mot de passe reste inchangé.\n\nUnivReq"
        )
    else:
        subject = _("[UnivReq] Activez votre compte — première connexion")
        body = _(
            "Bonjour %(name)s,\n\n"
            "Votre compte %(matricule)s est créé. Ouvrez le lien ci-dessous "
            "pour définir votre mot de passe et activer votre compte "
            "(valable %(hours)s heures, usage unique) :\n%(url)s\n\n"
            "Vous pourrez ensuite vous connecter avec votre matricule ou "
            "votre adresse e-mail.\n\nUnivReq"
        )

    send_mail(
        subject=str(subject),
        message=str(body)
        % {
            "name": user.get_full_name() or user.username,
            "matricule": user.username,
            "url": url,
            "hours": int(_ttl_for(purpose).total_seconds() // 3600),
        },
        from_email=None,
        recipient_list=[link_email_for(user)],
        # Échec visible côté serveur (jamais de jeton dans les logs).
        fail_silently=False,
    )
    logger.info(
        "E-mail d'accès envoyé (objet=%s, destinataire=%s, matricule=%s)",
        purpose,
        link_email_for(user),
        user.username,
    )
    return url


def link_email_for(user: User) -> str:
    return (user.email or "").strip()


__all__ = [
    "activation_ttl",
    "consume",
    "hash_token",
    "issue_link",
    "link_url",
    "reset_ttl",
    "resolve",
    "send_link_email",
    "site_base",
]
