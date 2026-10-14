"""Context processors globaux — core."""

from django.conf import settings


def vapid_public_key(request):
    """Expose la clé VAPID publique au template (abonnement Web Push client)."""
    return {"VAPID_PUBLIC_KEY": settings.VAPID_PUBLIC_KEY}
