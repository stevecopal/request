import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Identités, rôles et profils"

    def ready(self):
        """
        Garde-fou d'exploitation : en production, un backend e-mail « console »
        signifie que les liens de première connexion et de réinitialisation sont
        **imprimés dans les logs** au lieu d'être envoyés. On le rend visible
        dès le démarrage plutôt que de laisser croire que le mail part.
        """
        backend = getattr(settings, "EMAIL_BACKEND", "") or ""
        if settings.DEBUG or not backend.endswith("console.EmailBackend"):
            return
        logger.warning(
            "EMAIL_BACKEND=%s en production : les e-mails (première connexion, "
            "mot de passe oublié) sont imprimés dans les logs et ne sont PAS "
            "livrés. Configurez SMTP : EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, "
            "EMAIL_HOST_PASSWORD (+ DEFAULT_FROM_EMAIL et SITE_URL).",
            backend,
        )
