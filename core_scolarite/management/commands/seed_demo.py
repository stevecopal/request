"""
Commande de gestion `seed_demo` — jeu de démonstration UDS.

Reproduit la structure réelle de l'Université de Dschang : 8 établissements,
62 départements, programmes, UE, enseignants, étudiants, inscriptions,
services administratifs et types de problème du formulaire dynamique.

Idempotente (réexécutable sans doublon) et purge l'ancien jeu « Université
Nationale » le cas échéant. Aucun ticket de démonstration n'est créé.

Usage : uv run python manage.py seed_demo
"""

from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import (
    AcademicYear,
    Department,
    Faculty,
    Program,
    Student,
    StudentProgram,
    Teacher,
    University,
)
from core_scolarite.models import (
    AttachmentConfig,
    Course,
    Enrollment,
    ProblemType,
    Service,
    ServiceAssignment,
)
from tickets.models import Ticket

DEFAULT_UNIVERSITY = "Université de Dschang"
LEGACY_UNIVERSITY = "Université Nationale"
ACADEMIC_YEAR = "2025-2026"

# (établissement, [départements]) — source : univ-dschang.org (8 établissements)
STRUCTURE = [
    (
        "Faculté des Lettres et Sciences Humaines",
        [
            "Études Africaines et Mondialisation",
            "Géographie, Aménagement et Environnement",
            "Histoire et Archéologie",
            "Langues Étrangères Appliquées",
            "Lettres Bilingues",
            "Philosophie",
            "Psychologie",
            "Sociologie",
            "Sciences et Techniques de l'Information et de la Communication",
        ],
    ),
    (
        "Faculté des Sciences Économiques et de Gestion",
        [
            "Analyse et Politiques Économiques",
            "Économie Publique",
            "Économie du Développement",
            "Agribusiness",
            "Finance et Comptabilité",
            "Marketing et Management",
            "Entrepreneuriat et Innovation",
        ],
    ),
    (
        "Faculté des Sciences Juridiques et Politiques",
        [
            "Sciences politiques",
            "Droit pénal et sciences criminelles",
            "Droit privé fondamental",
            "Droit public",
            "Droit international et communautaire",
            "Droit des affaires et de l'entreprise",
            "English Law",
        ],
    ),
    (
        "Faculté des Sciences",
        [
            "Biologie Animale",
            "Biochimie",
            "Biologie Végétale",
            "Chimie",
            "Mathématiques-Informatique",
            "Physique",
            "Sciences de la Terre",
            "Sciences de l'Ingénieur",
        ],
    ),
    (
        "Faculté d'Agronomie et des Sciences Agricoles",
        [
            "Agriculture",
            "Foresterie",
            "Génie Rural",
            "Sciences du Sol",
            "Socio-Économie Rurale et Vulgarisation Agricole",
            "Zootechnie",
        ],
    ),
    (
        "Faculté de Médecine et des Sciences Pharmaceutiques",
        [
            "Physiology and Biochemistry",
            "Microbiologie, Hématologie et Immunologie",
            "Morphological Sciences, Pathological Anatomy and Legal Medicine",
            "Pharmaceutical Sciences",
            "Médecine Interne et Spécialités",
            "Pediatrics, Child and Adolescent",
            "Gynéco-Obstétrique et Santé Maternelle",
            "Surgery and Specialties, Anesthesia and Reanimation",
            "Ophtalmologie, ORL et Stomatologie (DOORLS)",
            "Public Health",
            "Radiology, Biophysics and Medical Imaging",
            "Physiotherapy and Physical Medicine",
        ],
    ),
    (
        "Institut Universitaire de Technologie Fotso Victor de Bandjoun",
        [
            "Enseignements Généraux et Scientifiques",
            "Génie Civil",
            "Génie Électrique",
            "Génie des Télécommunications et Réseaux",
            "Génie Informatique",
            "Génie Thermique, Énergie et Environnement",
            "Maintenance Industrielle et Productique",
            "Techniques de Commercialisation, Gestion Comptable et Financière",
        ],
    ),
    (
        "Institut des Beaux-Arts de Foumban",
        [
            "Architecture et Art de l'Ingénierie",
            "Arts Décoratifs",
            "Arts Technologie et Patrimoine",
            "Arts du Spectacle et Cinématographie",
            "Arts Plastiques et Histoire de l'Art",
        ],
    ),
]

# (matricule, titre, prénom, nom, département)
TEACHERS = [
    # Faculté des Sciences
    ("ENS001", "DR", "Paul", "Ndongo", "Mathématiques-Informatique"),
    ("ENS002", "PR", "Claire", "Mbala", "Mathématiques-Informatique"),
    ("ENS003", "MR", "Serge", "Kamdem", "Physique"),
    ("ENS004", "DR", "Alice", "Foka", "Chimie"),
    ("ENS005", "PR", "Jeanne", "Etoundi", "Biologie Animale"),
    ("ENS006", "MR", "Robert", "Njoya", "Sciences de la Terre"),
    ("ENS007", "DR", "Esther", "Bella", "Biochimie"),
    ("ENS008", "MR", "Samuel", "Ateba", "Biologie Végétale"),
    # Faculté des Sciences Juridiques et Politiques
    ("ENS009", "DR", "Ngo", "Bilie", "Droit privé fondamental"),
    ("ENS010", "PR", "Marie", "Tchouta", "Droit public"),
    ("ENS011", "DR", "Henri", "Owona", "Sciences politiques"),
    ("ENS012", "MR", "Alain", "Sedjo", "Droit des affaires et de l'entreprise"),
    # Faculté des Sciences Économiques et de Gestion
    ("ENS013", "DR", "Sophie", "Abena", "Analyse et Politiques Économiques"),
    ("ENS014", "MR", "Patrick", "Nkoulou", "Finance et Comptabilité"),
    ("ENS015", "MME", "Catherine", "Mvondo", "Marketing et Management"),
    ("ENS016", "DR", "Alphonse", "Djomo", "Économie du Développement"),
    ("ENS017", "MME", "Patrickine", "Beyeme", "Entrepreneuriat et Innovation"),
    # Faculté des Lettres et Sciences Humaines
    ("ENS018", "MME", "Bernadette", "Essomba", "Histoire et Archéologie"),
    ("ENS019", "DR", "Ivan", "Kuate", "Langues Étrangères Appliquées"),
    ("ENS020", "MME", "Ruth", "Ndam", "Géographie, Aménagement et Environnement"),
    ("ENS021", "MR", "Joseph", "Asong", "Sociologie"),
    ("ENS022", "MME", "Clarisse", "Nana", "Sciences et Techniques de l'Information et de la Communication"),
    # Faculté d'Agronomie et des Sciences Agricoles
    ("ENS023", "PR", "Salomon", "Talla", "Agriculture"),
    ("ENS024", "MME", "Véronique", "Ndasi", "Zootechnie"),
    ("ENS025", "MR", "Emmanuel", "Fru", "Génie Rural"),
    ("ENS026", "MME", "Léonie", "Tchoupo", "Sciences du Sol"),
    # Faculté de Médecine et des Sciences Pharmaceutiques
    ("ENS027", "DR", "Che", "Gibert", "Morphological Sciences, Pathological Anatomy and Legal Medicine"),
    ("ENS028", "PR", "Nadège", "Fouda", "Pharmaceutical Sciences"),
    # IUT Fotso Victor
    ("ENS029", "MR", "Bruno", "Kamga", "Génie Informatique"),
    # Institut des Beaux-Arts
    ("ENS030", "MME", "Solange", "Kouam", "Arts Plastiques et Histoire de l'Art"),
]

# (code, nom, département, matricule enseignant)
COURSES = [
    # Faculté des Sciences — Mathématiques-Informatique
    ("INF101", "Introduction à l'algorithmique", "Mathématiques-Informatique", "ENS001"),
    ("INF102", "Programmation orientée objet", "Mathématiques-Informatique", "ENS002"),
    ("INF201", "Structures de données et algorithmes", "Mathématiques-Informatique", "ENS002"),
    ("MAT111", "Analyse différentielle", "Mathématiques-Informatique", "ENS001"),
    ("MAT121", "Algèbre linéaire", "Mathématiques-Informatique", "ENS001"),
    ("PHY101", "Mécanique générale", "Physique", "ENS003"),
    ("CHI101", "Chimie générale", "Chimie", "ENS004"),
    ("BIO101", "Zoologie générale", "Biologie Animale", "ENS005"),
    ("BCH101", "Biochimie générale", "Biochimie", "ENS007"),
    ("BVE101", "Botanique générale", "Biologie Végétale", "ENS008"),
    ("STE101", "Géologie générale", "Sciences de la Terre", "ENS006"),
    # Faculté des Sciences Juridiques et Politiques
    ("DRO101", "Introduction au droit privé", "Droit privé fondamental", "ENS009"),
    ("DRO102", "Droit public", "Droit public", "ENS010"),
    ("DRO201", "Droit des affaires", "Droit des affaires et de l'entreprise", "ENS012"),
    ("POL101", "Introduction aux sciences politiques", "Sciences politiques", "ENS011"),
    # Faculté des Sciences Économiques et de Gestion
    ("ECO101", "Microéconomie", "Analyse et Politiques Économiques", "ENS013"),
    ("ECO111", "Économie du développement", "Économie du Développement", "ENS016"),
    ("GES101", "Principes de gestion", "Finance et Comptabilité", "ENS014"),
    ("GES121", "Comptabilité générale", "Finance et Comptabilité", "ENS014"),
    ("GES131", "Marketing fondamental", "Marketing et Management", "ENS015"),
    ("GES141", "Entrepreneuriat et innovation", "Entrepreneuriat et Innovation", "ENS017"),
    # Faculté des Lettres et Sciences Humaines
    ("HIS101", "Histoire du Cameroun", "Histoire et Archéologie", "ENS018"),
    ("ANG101", "Anglais général", "Langues Étrangères Appliquées", "ENS019"),
    ("GEO121", "Géographie du développement", "Géographie, Aménagement et Environnement", "ENS020"),
    ("SOC101", "Introduction à la sociologie", "Sociologie", "ENS021"),
    ("COM101", "Introduction aux sciences de l'information", "Sciences et Techniques de l'Information et de la Communication", "ENS022"),
    # Faculté d'Agronomie et des Sciences Agricoles
    ("AGR101", "Agronomie tropicale", "Agriculture", "ENS023"),
    ("ZOO101", "Zootechnie générale", "Zootechnie", "ENS024"),
    ("RUR101", "Génie rural : eau et énergie", "Génie Rural", "ENS025"),
    ("SAI101", "Sciences du sol générales", "Sciences du Sol", "ENS026"),
    # Faculté de Médecine et des Sciences Pharmaceutiques
    ("ANA101", "Anatomie générale", "Morphological Sciences, Pathological Anatomy and Legal Medicine", "ENS027"),
    ("PHA101", "Chimie pharmaceutique", "Pharmaceutical Sciences", "ENS028"),
    # IUT Fotso Victor
    ("IUT101", "Programmation et réseaux", "Génie Informatique", "ENS029"),
    # Institut des Beaux-Arts
    ("ART101", "Histoire de l'art", "Arts Plastiques et Histoire de l'Art", "ENS030"),
]

# (département, code programme, intitulé) — licence, pour les départements
# qui hébergent des étudiants du jeu de démonstration.
PROGRAMS = [
    ("Mathématiques-Informatique", "L-INFO", "Licence Informatique"),
    ("Physique", "L-PHYS", "Licence Physique"),
    ("Droit privé fondamental", "L-DROP", "Licence Droit Privé"),
    ("Droit public", "L-DROPU", "Licence Droit Public"),
    ("Finance et Comptabilité", "L-FICO", "Licence Finance et Comptabilité"),
    ("Marketing et Management", "L-MKT", "Licence Marketing"),
    ("Analyse et Politiques Économiques", "L-APE", "Licence Économie"),
    ("Histoire et Archéologie", "L-HIST", "Licence Histoire"),
    ("Langues Étrangères Appliquées", "L-LEA", "Licence Langues Étrangères Appliquées"),
    ("Agriculture", "L-AGRO", "Licence Agronomie"),
    ("Sciences du Sol", "L-SOL", "Licence Sciences du Sol"),
]

# (matricule, prénom, nom, email, département)
STUDENTS = [
    ("ETU001", "Alice", "Kamga", "alice.kamga@univ-dschang.org", "Mathématiques-Informatique"),
    ("ETU002", "Brice", "Tchoumi", "brice.tchoumi@univ-dschang.org", "Mathématiques-Informatique"),
    ("ETU003", "Chantal", "Eyenga", "chantal.eyenga@univ-dschang.org", "Physique"),
    ("ETU004", "David", "Nkongho", "david.nkongho@univ-dschang.org", "Droit privé fondamental"),
    ("ETU005", "Estelle", "Mbarga", "estelle.mbarga@univ-dschang.org", "Droit public"),
    ("ETU006", "Franck", "Atemengue", "franck.atemengue@univ-dschang.org", "Finance et Comptabilité"),
    ("ETU007", "Grâce", "Oyono", "grace.oyono@univ-dschang.org", "Marketing et Management"),
    ("ETU008", "Hervé", "Sipa", "herve.sipa@univ-dschang.org", "Analyse et Politiques Économiques"),
    ("ETU009", "Inès", "Zebaze", "ines.zebaze@univ-dschang.org", "Histoire et Archéologie"),
    ("ETU010", "Junior", "Belibi", "junior.belibi@univ-dschang.org", "Langues Étrangères Appliquées"),
    ("ETU011", "Karelle", "Ndongo", "karelle.ndongo@univ-dschang.org", "Agriculture"),
    ("ETU012", "Loïc", "Mballa", "loic.mballa@univ-dschang.org", "Sciences du Sol"),
]

# (matricule étudiant, code UE) — inscription en ACADEMIC_YEAR
ENROLLMENTS = [
    ("ETU001", "INF101"),
    ("ETU001", "INF102"),
    ("ETU001", "MAT111"),
    ("ETU001", "MAT121"),
    ("ETU002", "INF101"),
    ("ETU002", "INF102"),
    ("ETU002", "INF201"),
    ("ETU003", "PHY101"),
    ("ETU003", "MAT111"),
    ("ETU004", "DRO101"),
    ("ETU004", "DRO102"),
    ("ETU005", "DRO102"),
    ("ETU005", "POL101"),
    ("ETU006", "GES101"),
    ("ETU006", "GES121"),
    ("ETU006", "GES131"),
    ("ETU007", "GES131"),
    ("ETU007", "GES101"),
    ("ETU008", "ECO101"),
    ("ETU008", "ECO111"),
    ("ETU008", "GES101"),
    ("ETU009", "HIS101"),
    ("ETU009", "ANG101"),
    ("ETU010", "ANG101"),
    ("ETU010", "COM101"),
    ("ETU011", "AGR101"),
    ("ETU011", "ZOO101"),
    ("ETU012", "AGR101"),
    ("ETU012", "SAI101"),
]

# (nom, description, email de contact)
SERVICES = [
    (
        "Service des examens et notes",
        "Organisation des évaluations, délibérations et corrections.",
        "examens@univ-dschang.org",
    ),
    (
        "Scolarité et inscriptions",
        "Inscriptions administratives, attestations et relevés de notes.",
        "scolarite@univ-dschang.org",
    ),
    (
        "Systèmes d'information",
        "Portail étudiant, comptes utilisateurs et accès numériques.",
        "si@univ-dschang.org",
    ),
]

# (service, coordonnateur, [membres]) — matricules d'enseignants
SERVICE_ASSIGNMENTS = [
    ("Service des examens et notes", "ENS001", ["ENS002", "ENS013"]),
    ("Scolarité et inscriptions", "ENS018", ["ENS010", "ENS019"]),
    ("Systèmes d'information", "ENS029", ["ENS001"]),
]

# (nom, requires_course, description, service, [(libellé pièce, obligatoire)])
PROBLEM_TYPES = [
    (
        "Note manquante",
        True,
        "Votre note n'apparaît pas sur le portail.",
        "Service des examens et notes",
        [("Résultat du portail", True), ("Feuille d'émargement", True)],
    ),
    (
        "Double correction",
        True,
        "La même évaluation a été comptée deux fois.",
        "Service des examens et notes",
        [("Résultat du portail", True)],
    ),
    (
        "Absence justifiée",
        False,
        "Justifier une absence à une évaluation.",
        "Service des examens et notes",
        [("Justificatif médical", True)],
    ),
    (
        "Relevé de notes",
        False,
        "Demande de relevé de notes officiel.",
        "Scolarité et inscriptions",
        [],
    ),
    (
        "Attestation de scolarité",
        False,
        "Demande d'attestation administrative.",
        "Scolarité et inscriptions",
        [],
    ),
    (
        "Frais d'inscription",
        False,
        "Situation ou règlement des frais d'inscription.",
        "Scolarité et inscriptions",
        [("Preuve de paiement", True)],
    ),
    (
        "Accès au portail bloqué",
        False,
        "Vous ne pouvez plus accéder à votre compte du portail étudiant.",
        "Systèmes d'information",
        [("Capture d'écran", False)],
    ),
]


class Command(BaseCommand):
    help = "Crée le jeu de démonstration UDS (idempotent, sans tickets)."

    @transaction.atomic
    def handle(self, *args, **options):
        year = date.today().year
        pattern = settings.IMPORT_DEFAULT_PASSWORD_PATTERN

        def temp_password(matricule):
            return pattern.format(matricule=matricule, year=year)

        purged = self._purge_legacy()

        # ── Année académique courante ────────────────────────────────────
        ay, _ = AcademicYear.objects.get_or_create(
            code=ACADEMIC_YEAR,
            defaults={
                "start_date": date(2025, 10, 1),
                "end_date": date(2026, 7, 31),
            },
        )
        if not ay.is_current:
            ay.is_current = True
            ay.save()

        # ── Université, établissements, départements ─────────────────────
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

        # ── Services administratifs ──────────────────────────────────────
        services = {}
        for name, description, email in SERVICES:
            service, _ = Service.objects.get_or_create(
                university=university,
                name=name,
                defaults={"description": description, "contact_email": email},
            )
            services[name] = service

        # ── Enseignants ──────────────────────────────────────────────────
        teachers = {}
        for matricule, title, first, last, dept_name in TEACHERS:
            dept = departments[dept_name]
            user, _ = User.objects.get_or_create(
                username=matricule,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{matricule.lower()}@univ-dschang.org",
                },
            )
            user.set_password(temp_password(matricule))
            user.save()
            teacher, _ = Teacher.objects.get_or_create(
                user=user,
                defaults={
                    "title": title,
                    "faculty": dept.faculty,
                    "department": dept,
                },
            )
            teachers[matricule] = teacher

        # ── Programmes & UE ──────────────────────────────────────────────
        programs = {}
        for dept_name, code, name in PROGRAMS:
            dept = departments[dept_name]
            program, _ = Program.objects.get_or_create(
                department=dept,
                code=code,
                defaults={"name": name, "level": Program.Level.LICENCE},
            )
            programs[dept_name] = program

        courses = {}
        for code, name, dept_name, teacher_matricule in COURSES:
            dept = departments[dept_name]
            course, _ = Course.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "department": dept,
                    "program": programs.get(dept_name),
                    "primary_instructor": teachers[teacher_matricule],
                },
            )
            courses[code] = course

        # ── Étudiants & affectations programmes ──────────────────────────
        students = {}
        for matricule, first, last, email, dept_name in STUDENTS:
            user, _ = User.objects.get_or_create(
                username=matricule,
                defaults={"first_name": first, "last_name": last, "email": email},
            )
            user.set_password(temp_password(matricule))
            user.save()
            dept = departments[dept_name]
            student, _ = Student.objects.get_or_create(
                user=user,
                defaults={
                    "registration_number": matricule,
                    "faculty": dept.faculty,
                    "department": dept,
                },
            )
            students[matricule] = student
            StudentProgram.objects.get_or_create(
                student=student,
                program=programs[dept_name],
                academic_year=ay,
            )

        # ── Inscriptions (filtrage du formulaire dynamique) ──────────────
        for matricule, course_code in ENROLLMENTS:
            Enrollment.objects.get_or_create(
                student=students[matricule],
                course=courses[course_code],
                defaults={"academic_year": ACADEMIC_YEAR},
            )

        # ── Types de problème & règles de pièces jointes ─────────────────
        # Migration des anciens types globaux vers l'université : jamais de doublon.
        ProblemType.objects.filter(
            university__isnull=True,
            name__in=[spec[0] for spec in PROBLEM_TYPES],
        ).update(university=university)

        for position, spec in enumerate(PROBLEM_TYPES, start=1):
            pt_name, requires_course, description, service_name, attachments = spec
            pt, _ = ProblemType.objects.get_or_create(
                university=university,
                name=pt_name,
                defaults={
                    "description": description,
                    "requires_course": requires_course,
                    "service": services[service_name],
                    "position": position,
                },
            )
            # Synchronisation déterministe de la configuration à chaque run.
            pt.description = description
            pt.requires_course = requires_course
            pt.service = services[service_name]
            pt.position = position
            pt.is_active = True
            pt.save()
            for label, is_required in attachments:
                AttachmentConfig.objects.get_or_create(
                    problem_type=pt,
                    label=label,
                    defaults={"is_required": is_required},
                )

        # ── Affectations aux services ────────────────────────────────────
        for service_name, coordinator, members in SERVICE_ASSIGNMENTS:
            service = services[service_name]
            ServiceAssignment.objects.get_or_create(
                service=service,
                user=teachers[coordinator].user,
                defaults={"role": ServiceAssignment.Role.COORDINATOR},
            )
            for matricule in members:
                ServiceAssignment.objects.get_or_create(
                    service=service,
                    user=teachers[matricule].user,
                    defaults={"role": ServiceAssignment.Role.MEMBER},
                )

        # ── Super-admin ──────────────────────────────────────────────────
        admin_user, created = User.objects.get_or_create(
            username="ADMIN001",
            defaults={
                "first_name": "Super",
                "last_name": "Admin",
                "email": "admin@univ-dschang.org",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin_user.set_password(temp_password("ADMIN001"))
            admin_user.save()

        # ── Bilan ────────────────────────────────────────────────────────
        if purged:
            self.stdout.write(f"Ancien jeu « {LEGACY_UNIVERSITY} » purgé.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Jeu de démonstration UDS prêt : {len(STRUCTURE)} établissements, "
                f"{len(departments)} départements, {len(programs)} programmes, "
                f"{len(courses)} UE, {len(teachers)} enseignants, "
                f"{len(students)} étudiants, {len(ENROLLMENTS)} inscriptions, "
                f"{len(SERVICES)} services, {len(PROBLEM_TYPES)} types de problème."
            )
        )
        self.stdout.write(
            "Comptes (mot de passe = règle IMPORT_DEFAULT_PASSWORD_PATTERN) :\n"
            "  étudiants    ETU001 → ETU012\n"
            "  enseignants  ENS001 → ENS030\n"
            "  super-admin  ADMIN001"
        )

    def _purge_legacy(self) -> bool:
        """
        Supprime l'ancien jeu « Université Nationale » (démo précédente).

        Ordonné pour satisfaire les contraintes PROTECT : tickets →
        enseignants → étudiants → UE/programmes → types de problème →
        services → facultés (cascade des départements) → université.
        Les comptes Django sont conservés et réutilisés par le nouveau jeu.
        """
        from django.db.models import Q  # import local : évite toute boucle d'imports

        legacy = University.objects.filter(name=LEGACY_UNIVERSITY).first()
        if legacy is None:
            return False
        legacy_students = Student.objects.filter(
            Q(faculty__university=legacy) | Q(department__faculty__university=legacy)
        )
        legacy_teachers = Teacher.objects.filter(faculty__university=legacy)
        legacy_courses = Course.objects.filter(department__faculty__university=legacy)
        # Les tickets (et tout leur historique) partent en premier.
        Ticket.objects.filter(
            Q(student__in=legacy_students)
            | Q(teacher__in=legacy_teachers)
            | Q(course__in=legacy_courses)
            | Q(problem_type__university=legacy)
        ).delete()
        legacy_teachers.delete()  # après les tickets (PROTECT)
        legacy_students.delete()
        legacy_courses.delete()
        Program.objects.filter(department__faculty__university=legacy).delete()
        ProblemType.objects.filter(university=legacy).delete()
        Service.objects.filter(university=legacy).delete()
        # Faculty.university est PROTECT : on supprime les facultés (ce qui
        # emporte leurs départements en cascade) avant l'université.
        Faculty.objects.filter(university=legacy).delete()
        legacy.delete()
        return True




