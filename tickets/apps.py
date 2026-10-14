from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tickets"
    verbose_name = "Requêtes, statuts et temps réel"

    def ready(self):
        # Phase 8 : branche les signaux post_save(Ticket) → broadcast Channels.
        from tickets import signals  # noqa: F401
