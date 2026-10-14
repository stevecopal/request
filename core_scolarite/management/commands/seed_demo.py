"""
Commande de gestion `seed_demo` — jeu de données de démonstration.

Idempotente : réexécutable sans créer de doublons (`get_or_create` partout).
Crée facultés, départements, UE, types de problème + règles de pièces jointes
et un compte de démo pour chaque rôle (étudiant, enseignant, super-admin).

Usage : uv run python manage.py seed_demo
"""

from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Department, Faculty, Student, Teacher, University
from core_scolarite.models import AttachmentConfig, Course, ProblemType

DEFAULT_UNIVERSITY = "Université Nationale"

# (faculté, [départements])
STRUCTURE = [
    ("Faculté des Sciences", ["Informatique", "Mathématiques", "Physique"]),
    ("Faculté des Lettres et Sciences Humaines", ["Lettres Modernes", "Histoire"]),
]

# (code, nom, département, (titre, matricule_user, prénom, nom))
COURSES = [
    ("INF101", "Introduction à l'algorithmique", "Informatique",
     ("DR", "ENS001", "Paul", "Ndongo")),
    ("MAT210", "Algèbre linéaire", "Mathématiques",
     ("PR", "ENS002", "Claire", "Mbala")),
]

# (nom, requires_course, description, [(label, is_required)])
PROBLEM_TYPES = [
    ("Note manquante", True,
     "Votre note n'apparaît pas sur le portail.",
     [("Résultat du portail", True), ("Feuille d'émargement", True)]),
    ("Double correction", True,
     "La même évaluation a été comptée deux fois.",
     [("Résultat du portail", True)]),
    ("Absence justifiée", False,
     "Justifier une absence à une évaluation.",
     [("Justificatif médical", True)]),
    ("Attestation de scolarité", False,
     "Demande d'attestation administrative.", []),
]

# (matricule, prénom, nom, email, faculté, département)
STUDENTS = [
    ("ETU001", "Alice", "Kamga", "alice.kamga@univ.example", "Faculté des Sciences", "Informatique"),
    ("ETU002", "Brice", "Tchoumi", "brice.tchoumi@univ.example", "Faculté des Sciences", "Mathématiques"),
]


class Command(BaseCommand):
    help = "Crée un jeu de données de démonstration (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        year = date.today().year
        pattern = settings.IMPORT_DEFAULT_PASSWORD_PATTERN

        def temp_password(matricule):
            return pattern.format(matricule=matricule, year=year)

        # ── Université & facultés/départements ───────────────────────────
        university, _ = University.objects.get_or_create(name=DEFAULT_UNIVERSITY)
        departments = {}
        for faculty_name, dept_names in STRUCTURE:
            faculty, _ = Faculty.objects.get_or_create(
                university=university, name=faculty_name
            )
            for dept_name in dept_names:
                dept, _ = Department.objects.get_or_create(
                    faculty=faculty, name=dept_name
                )
                departments[dept_name] = dept

        # ── Enseignants & UE ─────────────────────────────────────────────
        for code, name, dept_name, (title, matricule, first, last) in COURSES:
            dept = departments[dept_name]
            user, _ = User.objects.get_or_create(
                username=matricule,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{matricule.lower()}@univ.example",
                },
            )
            user.set_password(temp_password(matricule))
            user.save()
            teacher, _ = Teacher.objects.get_or_create(
                user=user,
                defaults={"title": title, "faculty": dept.faculty, "department": dept},
            )
            Course.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "department": dept,
                    "primary_instructor": teacher,
                },
            )

        # ── Types de problème & règles de pièces jointes ─────────────────
        for pt_name, requires_course, description, attachments in PROBLEM_TYPES:
            pt, _ = ProblemType.objects.get_or_create(
                name=pt_name,
                defaults={"requires_course": requires_course, "description": description},
            )
            for label, is_required in attachments:
                AttachmentConfig.objects.get_or_create(
                    problem_type=pt, label=label, defaults={"is_required": is_required}
                )

        # ── Étudiants ────────────────────────────────────────────────────
        for matricule, first, last, email, faculty_name, dept_name in STUDENTS:
            user, _ = User.objects.get_or_create(
                username=matricule,
                defaults={"first_name": first, "last_name": last, "email": email},
            )
            user.set_password(temp_password(matricule))
            user.save()
            dept = departments[dept_name]
            Student.objects.get_or_create(
                user=user,
                defaults={
                    "registration_number": matricule,
                    "faculty": dept.faculty,
                    "department": dept,
                },
            )

        # ── Super-admin ──────────────────────────────────────────────────
        admin_user, created = User.objects.get_or_create(
            username="ADMIN001",
            defaults={
                "first_name": "Super",
                "last_name": "Admin",
                "email": "admin@univ.example",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin_user.set_password(temp_password("ADMIN001"))
            admin_user.save()

        self.stdout.write(self.style.SUCCESS("Jeu de démonstration prêt."))
        self.stdout.write(
            "Comptes (mot de passe = règle IMPORT_DEFAULT_PASSWORD_PATTERN) :\n"
            "  étudiant    ETU001 / ETU002\n"
            "  enseignants ENS001 / ENS002\n"
            "  super-admin ADMIN001"
        )
