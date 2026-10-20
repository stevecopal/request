"""
Commande de gestion `seed_demo` — jeu de démonstration UDS.

Reproduit la structure réelle de l'Université de Dschang : 8 établissements,
62 départements, programmes, UE, enseignants, étudiants, inscriptions,
services administratifs et types de problème du formulaire dynamique.

Matricules **au format officiel** (accounts.services.matricules) :
  * étudiant   : `CM-UDS-25SCI0001` (code de faculté + numéro d'ordre)
  * enseignant : `CM-UDS-25ENS0001` (segment enseignant configuré)
Les codes de faculté (liste officielle) sont attribués à chaque établissement.

Idempotent **et sans doublon** : à chaque chargement, l'ancien jeu UDS est
purgé (tickets, comptes de démo, profils, UE, programmes, services, types de
problème, facultés/départements) puis entièrement recréé. L'ancien jeu
« Université Nationale » est purgé lui aussi. Aucun ticket de démonstration
n'est créé.

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
from accounts.services import matricules
from core_scolarite.models import (
    AttachmentConfig,
    Course,
    CourseAssignment,
    Enrollment,
    ProblemType,
    Service,
    ServiceAssignment,
)
from tickets.models import Ticket

DEFAULT_UNIVERSITY = "Université de Dschang"
LEGACY_UNIVERSITY = "Université Nationale"
ACADEMIC_YEAR = "2025-2026"

# Codes officiels des établissements (liste configurée — console C2).
FACULTY_CODES = {
    "Faculté des Lettres et Sciences Humaines": "LSH",
    "Faculté des Sciences Économiques et de Gestion": "SEG",
    "Faculté des Sciences Juridiques et Politiques": "SJP",
    "Faculté des Sciences": "SCI",
    "Faculté d'Agronomie et des Sciences Agricoles": "ASA",
    "Faculté de Médecine et des Sciences Pharmaceutiques": "MSP",
    "Institut Universitaire de Technologie Fotso Victor de Bandjoun": "IUT",
    "Institut des Beaux-Arts de Foumban": "IBA",
}

# Année d'inscription codée dans les matricules du jeu (année académique
# courante du seed). Blocs : pays CM, université UDS, année 25.
YEAR_BLOCK = "25"


def M(segment: str, number: int) -> str:
    """Matricule officiel du jeu : M("SCI", 1) → « CM-UDS-25SCI0001 »."""
    return f"CM-UDS-{YEAR_BLOCK}{segment}{number:04d}"


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
    (M("ENS", 1), "DR", "Paul", "Ndongo", "Mathématiques-Informatique"),
    (M("ENS", 2), "PR", "Claire", "Mbala", "Mathématiques-Informatique"),
    (M("ENS", 3), "MR", "Serge", "Kamdem", "Physique"),
    (M("ENS", 4), "DR", "Alice", "Foka", "Chimie"),
    (M("ENS", 5), "PR", "Jeanne", "Etoundi", "Biologie Animale"),
    (M("ENS", 6), "MR", "Robert", "Njoya", "Sciences de la Terre"),
    (M("ENS", 7), "DR", "Esther", "Bella", "Biochimie"),
    (M("ENS", 8), "MR", "Samuel", "Ateba", "Biologie Végétale"),
    # Faculté des Sciences Juridiques et Politiques
    (M("ENS", 9), "DR", "Ngo", "Bilie", "Droit privé fondamental"),
    (M("ENS", 10), "PR", "Marie", "Tchouta", "Droit public"),
    (M("ENS", 11), "DR", "Henri", "Owona", "Sciences politiques"),
    (M("ENS", 12), "MR", "Alain", "Sedjo", "Droit des affaires et de l'entreprise"),
    # Faculté des Sciences Économiques et de Gestion
    (M("ENS", 13), "DR", "Sophie", "Abena", "Analyse et Politiques Économiques"),
    (M("ENS", 14), "MR", "Patrick", "Nkoulou", "Finance et Comptabilité"),
    (M("ENS", 15), "MME", "Catherine", "Mvondo", "Marketing et Management"),
    (M("ENS", 16), "DR", "Alphonse", "Djomo", "Économie du Développement"),
    (M("ENS", 17), "MME", "Patrickine", "Beyeme", "Entrepreneuriat et Innovation"),
    # Faculté des Lettres et Sciences Humaines
    (M("ENS", 18), "MME", "Bernadette", "Essomba", "Histoire et Archéologie"),
    (M("ENS", 19), "DR", "Ivan", "Kuate", "Langues Étrangères Appliquées"),
    (M("ENS", 20), "MME", "Ruth", "Ndam", "Géographie, Aménagement et Environnement"),
    (M("ENS", 21), "MR", "Joseph", "Asong", "Sociologie"),
    (M("ENS", 22), "MME", "Clarisse", "Nana", "Sciences et Techniques de l'Information et de la Communication"),
    # Faculté d'Agronomie et des Sciences Agricoles
    (M("ENS", 23), "PR", "Salomon", "Talla", "Agriculture"),
    (M("ENS", 24), "MME", "Véronique", "Ndasi", "Zootechnie"),
    (M("ENS", 25), "MR", "Emmanuel", "Fru", "Génie Rural"),
    (M("ENS", 26), "MME", "Léonie", "Tchoupo", "Sciences du Sol"),
    # Faculté de Médecine et des Sciences Pharmaceutiques
    (M("ENS", 27), "DR", "Che", "Gibert", "Morphological Sciences, Pathological Anatomy and Legal Medicine"),
    (M("ENS", 28), "PR", "Nadège", "Fouda", "Pharmaceutical Sciences"),
    # IUT Fotso Victor
    (M("ENS", 29), "MR", "Bruno", "Kamga", "Génie Informatique"),
    # Institut des Beaux-Arts
    (M("ENS", 30), "MME", "Solange", "Kouam", "Arts Plastiques et Histoire de l'Art"),
]

# (code, nom, département, matricule enseignant)
COURSES = [
    # Faculté des Sciences — Mathématiques-Informatique
    ("INF101", "Introduction à l'algorithmique", "Mathématiques-Informatique", M("ENS", 1)),
    ("INF102", "Programmation orientée objet", "Mathématiques-Informatique", M("ENS", 2)),
    ("INF201", "Structures de données et algorithmes", "Mathématiques-Informatique", M("ENS", 2)),
    ("MAT111", "Analyse différentielle", "Mathématiques-Informatique", M("ENS", 1)),
    ("MAT121", "Algèbre linéaire", "Mathématiques-Informatique", M("ENS", 1)),
    ("PHY101", "Mécanique générale", "Physique", M("ENS", 3)),
    ("CHI101", "Chimie générale", "Chimie", M("ENS", 4)),
    ("BIO101", "Zoologie générale", "Biologie Animale", M("ENS", 5)),
    ("BCH101", "Biochimie générale", "Biochimie", M("ENS", 7)),
    ("BVE101", "Botanique générale", "Biologie Végétale", M("ENS", 8)),
    ("STE101", "Géologie générale", "Sciences de la Terre", M("ENS", 6)),
    # Faculté des Sciences Juridiques et Politiques
    ("DRO101", "Introduction au droit privé", "Droit privé fondamental", M("ENS", 9)),
    ("DRO102", "Droit public", "Droit public", M("ENS", 10)),
    ("DRO201", "Droit des affaires", "Droit des affaires et de l'entreprise", M("ENS", 12)),
    ("POL101", "Introduction aux sciences politiques", "Sciences politiques", M("ENS", 11)),
    # Faculté des Sciences Économiques et de Gestion
    ("ECO101", "Microéconomie", "Analyse et Politiques Économiques", M("ENS", 13)),
    ("ECO111", "Économie du développement", "Économie du Développement", M("ENS", 16)),
    ("GES101", "Principes de gestion", "Finance et Comptabilité", M("ENS", 14)),
    ("GES121", "Comptabilité générale", "Finance et Comptabilité", M("ENS", 14)),
    ("GES131", "Marketing fondamental", "Marketing et Management", M("ENS", 15)),
    ("GES141", "Entrepreneuriat et innovation", "Entrepreneuriat et Innovation", M("ENS", 17)),
    # Faculté des Lettres et Sciences Humaines
    ("HIS101", "Histoire du Cameroun", "Histoire et Archéologie", M("ENS", 18)),
    ("ANG101", "Anglais général", "Langues Étrangères Appliquées", M("ENS", 19)),
    ("GEO121", "Géographie du développement", "Géographie, Aménagement et Environnement", M("ENS", 20)),
    ("SOC101", "Introduction à la sociologie", "Sociologie", M("ENS", 21)),
    ("COM101", "Introduction aux sciences de l'information", "Sciences et Techniques de l'Information et de la Communication", M("ENS", 22)),
    # Faculté d'Agronomie et des Sciences Agricoles
    ("AGR101", "Agronomie tropicale", "Agriculture", M("ENS", 23)),
    ("ZOO101", "Zootechnie générale", "Zootechnie", M("ENS", 24)),
    ("RUR101", "Génie rural : eau et énergie", "Génie Rural", M("ENS", 25)),
    ("SAI101", "Sciences du sol générales", "Sciences du Sol", M("ENS", 26)),
    # Faculté de Médecine et des Sciences Pharmaceutiques
    ("ANA101", "Anatomie générale", "Morphological Sciences, Pathological Anatomy and Legal Medicine", M("ENS", 27)),
    ("PHA101", "Chimie pharmaceutique", "Pharmaceutical Sciences", M("ENS", 28)),
    # IUT Fotso Victor
    ("IUT101", "Programmation et réseaux", "Génie Informatique", M("ENS", 29)),
    # Institut des Beaux-Arts
    ("ART101", "Histoire de l'art", "Arts Plastiques et Histoire de l'Art", M("ENS", 30)),
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
    (M("SCI", 1), "Alice", "Kamga", "alice.kamga@univ-dschang.org", "Mathématiques-Informatique"),
    (M("SCI", 2), "Brice", "Tchoumi", "brice.tchoumi@univ-dschang.org", "Mathématiques-Informatique"),
    (M("SCI", 3), "Chantal", "Eyenga", "chantal.eyenga@univ-dschang.org", "Physique"),
    (M("SJP", 4), "David", "Nkongho", "david.nkongho@univ-dschang.org", "Droit privé fondamental"),
    (M("SJP", 5), "Estelle", "Mbarga", "estelle.mbarga@univ-dschang.org", "Droit public"),
    (M("SEG", 6), "Franck", "Atemengue", "franck.atemengue@univ-dschang.org", "Finance et Comptabilité"),
    (M("SEG", 7), "Grâce", "Oyono", "grace.oyono@univ-dschang.org", "Marketing et Management"),
    (M("SEG", 8), "Hervé", "Sipa", "herve.sipa@univ-dschang.org", "Analyse et Politiques Économiques"),
    (M("LSH", 9), "Inès", "Zebaze", "ines.zebaze@univ-dschang.org", "Histoire et Archéologie"),
    (M("LSH", 10), "Junior", "Belibi", "junior.belibi@univ-dschang.org", "Langues Étrangères Appliquées"),
    (M("ASA", 11), "Karelle", "Ndongo", "karelle.ndongo@univ-dschang.org", "Agriculture"),
    (M("ASA", 12), "Loïc", "Mballa", "loic.mballa@univ-dschang.org", "Sciences du Sol"),
]

# (matricule étudiant, code UE) — inscription en ACADEMIC_YEAR
ENROLLMENTS = [
    (M("SCI", 1), "INF101"),
    (M("SCI", 1), "INF102"),
    (M("SCI", 1), "MAT111"),
    (M("SCI", 1), "MAT121"),
    (M("SCI", 2), "INF101"),
    (M("SCI", 2), "INF102"),
    (M("SCI", 2), "INF201"),
    (M("SCI", 3), "PHY101"),
    (M("SCI", 3), "MAT111"),
    (M("SJP", 4), "DRO101"),
    (M("SJP", 4), "DRO102"),
    (M("SJP", 5), "DRO102"),
    (M("SJP", 5), "POL101"),
    (M("SEG", 6), "GES101"),
    (M("SEG", 6), "GES121"),
    (M("SEG", 6), "GES131"),
    (M("SEG", 7), "GES131"),
    (M("SEG", 7), "GES101"),
    (M("SEG", 8), "ECO101"),
    (M("SEG", 8), "ECO111"),
    (M("SEG", 8), "GES101"),
    (M("LSH", 9), "HIS101"),
    (M("LSH", 9), "ANG101"),
    (M("LSH", 10), "ANG101"),
    (M("LSH", 10), "COM101"),
    (M("ASA", 11), "AGR101"),
    (M("ASA", 11), "ZOO101"),
    (M("ASA", 12), "AGR101"),
    (M("ASA", 12), "SAI101"),
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
    ("Service des examens et notes", M("ENS", 1), [M("ENS", 2), M("ENS", 13)]),
    ("Scolarité et inscriptions", M("ENS", 18), [M("ENS", 10), M("ENS", 19)]),
    ("Systèmes d'information", M("ENS", 29), [M("ENS", 1)]),
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

        purged_legacy = self._purge_legacy()
        purged_demo = self._purge_demo()

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
        university, _ = University.objects.get_or_create(
            name=DEFAULT_UNIVERSITY,
            defaults={"country_code": "CM", "code": "UDS"},
        )
        if university.country_code != "CM" or university.code != "UDS":
            university.country_code, university.code = "CM", "UDS"
            university.save(update_fields=["country_code", "code"])

        departments = {}
        for faculty_name, dept_names in STRUCTURE:
            # Code officiel de l'établissement (liste configurée, console C2).
            code = FACULTY_CODES.get(faculty_name, "")
            faculty, _ = Faculty.objects.get_or_create(
                university=university, name=faculty_name, defaults={"code": code}
            )
            if faculty.code != code:  # aligne la liste officielle à chaque run
                faculty.code = code
                faculty.save(update_fields=["code"])
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
        # Matricules officiels (CM-UDS-25ENS0001) définis dans TEACHERS.
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
        # Matricules officiels (CM-UDS-25SCI0001) définis dans STUDENTS.
        students = {}
        for matricule, first, last, email, dept_name in STUDENTS:
            dept = departments[dept_name]
            user, _ = User.objects.get_or_create(
                username=matricule,
                defaults={"first_name": first, "last_name": last, "email": email},
            )
            user.set_password(temp_password(matricule))
            user.save()
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
        # Contrôle de cohérence : chaque matricule du jeu respecte le format
        # officiel (pays-université-année-segment-numéro).
        for matricule, _first, _last, _email, dept_name in STUDENTS:
            matricules.validate(
                matricule,
                entity="students",
                university=university,
                faculty=departments[dept_name].faculty,
            )
        for teacher_row in TEACHERS:
            matricules.validate(
                teacher_row[0], entity="teachers", university=university
            )

        if purged_legacy:
            self.stdout.write(f"Ancien jeu « {LEGACY_UNIVERSITY} » purgé.")
        if purged_demo:
            self.stdout.write(
                f"Jeu précédent « {DEFAULT_UNIVERSITY} » vidé puis recréé "
                "(aucun doublon au chargement)."
            )
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
            "Comptes générés au format officiel "
            "(jeu de démo : mot de passe = règle IMPORT_DEFAULT_PASSWORD_PATTERN ; "
            "en production, les comptes créés démarrent inactifs et s'activent "
            "par lien de première connexion) :\n"
            "  super-admin  ADMIN001\n"
            f"  étudiants    {STUDENTS[0][0]} → {STUDENTS[-1][0]} ({len(STUDENTS)})\n"
            f"  enseignants  {TEACHERS[0][0]} → {TEACHERS[-1][0]} ({len(TEACHERS)})"
        )

    def _purge_demo(self) -> bool:
        """
        Vide le jeu de démonstration UDS avant régénération.

        Objectif « aucun doublon au chargement » : à chaque exécution, le jeu
        complet (tickets, inscriptions, affectations, enseignants, étudiants,
        UE, programmes, services, types de problème, facultés/départements)
        est supprimé, ainsi que les **comptes de démonstration** associés
        (jamais un compte super-admin ni un compte rattaché à une autre
        université).
        """
        from django.db.models import Q  # import local : évite toute boucle d'imports

        demo = University.objects.filter(name=DEFAULT_UNIVERSITY).first()
        if demo is None:
            return False

        students = Student.objects.filter(
            Q(faculty__university=demo) | Q(department__faculty__university=demo)
        )
        teachers = Teacher.objects.filter(faculty__university=demo)
        courses = Course.objects.filter(department__faculty__university=demo)
        student_ids = list(students.values_list("id", flat=True))
        teacher_ids = list(teachers.values_list("id", flat=True))

        # Comptes de démo concernés (profils → comptes, jamais d'admin).
        demo_users = list(
            User.objects.filter(
                Q(student_profile__id__in=student_ids)
                | Q(teacher_profile__id__in=teacher_ids)
            )
            .distinct()
            .values_list("id", flat=True)
        )

        deleted_tickets = Ticket.objects.filter(
            Q(student_id__in=student_ids)
            | Q(teacher_id__in=teacher_ids)
            | Q(course__in=courses)
            | Q(problem_type__university=demo)
        ).count()

        # Ordonnancement satisfaisant les contraintes PROTECT.
        Ticket.objects.filter(
            Q(student_id__in=student_ids)
            | Q(teacher_id__in=teacher_ids)
            | Q(course__in=courses)
            | Q(problem_type__university=demo)
        ).delete()
        Enrollment.objects.filter(student_id__in=student_ids).delete()
        CourseAssignment.objects.filter(course__in=courses).delete()
        ServiceAssignment.objects.filter(service__university=demo).delete()
        StudentProgram.objects.filter(student_id__in=student_ids).delete()
        teachers.delete()
        students.delete()
        courses.delete()
        Program.objects.filter(department__faculty__university=demo).delete()
        ProblemType.objects.filter(university=demo).delete()
        Service.objects.filter(university=demo).delete()
        # Faculty.university est PROTECT : facultés (cascade des départements)
        # supprimées avant l'université.
        Faculty.objects.filter(university=demo).delete()
        demo.delete()

        User.objects.filter(id__in=demo_users).exclude(
            Q(is_superuser=True) | Q(is_staff=True)
        ).delete()

        self.stdout.write(
            f"Jeu UDS précédent vidé : {deleted_tickets} ticket(s), "
            f"{len(teacher_ids)} enseignant(s), {len(student_ids)} étudiant(s), "
            f"{len(demo_users)} compte(s) supprimé(s)."
        )
        return True

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




