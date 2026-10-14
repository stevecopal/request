"""Web Push — envoi de notifications hors-page (best-effort, jamais bloquant)."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """True si les clés VAPID sont présentes (push opérationnel)."""
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def save_subscription(user, subscription: dict) -> None:
    """Crée ou met à jour l'abonnement push de l'utilisateur connecté."""
    from accounts.models import PushSubscription

    endpoint = str(subscription.get("endpoint") or "")[:500]
    keys = subscription.get("keys") or {}
    if not endpoint:
        raise ValueError("endpoint manquant")
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh": str(keys.get("p256dh") or "")[:255],
            "auth": str(keys.get("auth") or "")[:255],
        },
    )


def remove_subscription(user, subscription: dict) -> None:
    """Supprime l'abonnement de l'utilisateur (jamais celui d'un autre)."""
    from accounts.models import PushSubscription

    endpoint = str(subscription.get("endpoint") or "")[:500]
    PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()


def send_to_user(user, title: str, body: str, tag: str = "", url: str = "/dashboard/") -> int:
    """
    Envoie une notification Web Push à tous les appareils d'un utilisateur.

    :param user: instance User ou user_id (int).
    :return: nombre d'appareils notifiés (best-effort).
    """
    if not is_configured():
        return 0
    from accounts.models import PushSubscription

    if isinstance(user, User):
        user_id = user.id
    else:
        user_id = user

    delivered = 0
    subscriptions = PushSubscription.objects.filter(user_id=user_id)
    for subscription in subscriptions:
        try:
            from pywebpush import WebPushException, webpush

            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(
                    {"title": title, "body": body, "tag": tag, "url": url}
                ),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"},
            )
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — best-effort jamais bloquant
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                # Abonnement expiré/révoqué côté navigateur : purge.
                subscription.delete()
                continue
            logger.warning("Web Push échoué (%s) : %s", user_id, exc)
    return delivered
