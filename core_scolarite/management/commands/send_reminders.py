"""
Commande `send_reminders` — envoi des relances configurées (ReminderPolicy).

Usage :
    python manage.py send_reminders                # envoie toutes les relances actives
    python manage.py send_reminders --dry-run      # aperçu sans écriture
    python manage.py send_reminders --university <uuid>
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from accounts.models import University
from core_scolarite.models import ReminderPolicy
from core_scolarite.services.reminders import collect_due, send_due
from core_scolarite.services.scoping import parse_uuid


class Command(BaseCommand):
    help = "Envoie les relances configurées (ReminderPolicy) aux destinataires."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les relances éligibles sans rien envoyer.",
        )
        parser.add_argument(
            "--university",
            default=None,
            help="Limiter à une université (UUID).",
        )

    def handle(self, *args, **options):
        university = None
        university_id = parse_uuid(options.get("university"))
        if university_id is not None:
            university = University.objects.filter(pk=university_id).first()

        dry_run = options["dry_run"]
        policies = ReminderPolicy.objects.filter(is_active=True).order_by("name")
        if not policies.exists():
            self.stdout.write(_("Aucune relance active."))
            return

        total = 0
        for policy in policies:
            due = collect_due(policy, university or policy.university)
            if dry_run:
                self.stdout.write(
                    f"[aperçu] {policy.name} : {len(due)} relance(s) éligible(s)."
                )
                for ticket, recipient in due:
                    self.stdout.write(
                        f"    - {ticket.short_id} → {recipient.username}"
                    )
                continue
            sent = send_due(due, policy)
            total += sent
            self.stdout.write(f"{policy.name} : {sent} relance(s) envoyée(s).")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Total : {total} relance(s)."))
