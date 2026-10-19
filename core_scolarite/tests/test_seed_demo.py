"""Tests de la commande `seed_demo` — jeu de démonstration UDS complet."""

import io

from django.core.management import call_command
from django.test import TestCase

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


class SeedDemoTests(TestCase):
    """`seed_demo` : structure UDS complète, idempotente, sans tickets."""

    def _seed(self):
        out = io.StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def test_seed_creates_full_dschang_structure(self):
        self._seed()
        uni = University.objects.get(name="Université de Dschang")
        self.assertEqual(Faculty.objects.filter(university=uni).count(), 8)
        self.assertEqual(
            Department.objects.filter(faculty__university=uni).count(), 62
        )
        self.assertEqual(Program.objects.count(), 11)
        self.assertEqual(Course.objects.count(), 34)
        self.assertEqual(Teacher.objects.count(), 30)
        self.assertEqual(Student.objects.count(), 12)
        self.assertEqual(StudentProgram.objects.count(), 12)
        self.assertEqual(Enrollment.objects.count(), 29)
        self.assertEqual(Service.objects.filter(university=uni).count(), 3)
        self.assertEqual(ServiceAssignment.objects.count(), 8)
        self.assertEqual(AttachmentConfig.objects.count(), 6)

        # Types de problème rattachés à l'université + 2 nouveaux types.
        self.assertEqual(ProblemType.visible_to(uni).count(), 7)
        self.assertEqual(ProblemType.visible_to(uni).filter(university=uni).count(), 7)
        note_pt = ProblemType.objects.get(university=uni, name="Note manquante")
        self.assertIsNotNone(note_pt.service_id)
        self.assertTrue(note_pt.requires_course)

        # Année académique courante.
        ay = AcademicYear.current()
        self.assertIsNotNone(ay)
        self.assertEqual(ay.code, "2025-2026")

        # Aucun ticket de démonstration.
        self.assertEqual(Ticket.objects.count(), 0)

    def test_seed_is_idempotent(self):
        self._seed()
        out = self._seed()
        self.assertEqual(University.objects.filter(name="Université de Dschang").count(), 1)
        self.assertEqual(Faculty.objects.count(), 8)
        self.assertEqual(Department.objects.count(), 62)
        self.assertEqual(Course.objects.filter(code="INF101").count(), 1)
        self.assertEqual(Student.objects.filter(user__username="ETU001").count(), 1)
        self.assertEqual(Enrollment.objects.count(), 29)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertIn("Jeu de démonstration UDS prêt", out)

    def test_seed_purges_legacy_demo_university(self):
        from django.contrib.auth.models import User

        from accounts.models import University as Uni

        # Créée par la migration 0002 ; le seed la purge au profit de l'UDS.
        legacy = Uni.objects.get(name="Université Nationale")
        faculty = Faculty.objects.create(university=legacy, name="Faculté des Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        teacher_user = User.objects.create_user(username="ENS001", password="x")
        teacher = Teacher.objects.create(
            user=teacher_user, title="DR", faculty=faculty, department=dept
        )
        student_user = User.objects.create_user(username="ETU001", password="x")
        student = Student.objects.create(
            user=student_user, registration_number="ETU001",
            faculty=faculty, department=dept,
        )
        course = Course.objects.create(code="INF101", name="Ancien programme", department=dept)
        old_pt = ProblemType.objects.create(university=legacy, name="Ancien type")
        Ticket.objects.create(
            student=student, teacher=teacher, problem_type=old_pt,
            description="Ticket de l'ancienne démo.",
        )

        self._seed()

        self.assertFalse(Uni.objects.filter(name="Université Nationale").exists())
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(
            Course.objects.get(code="INF101").department.faculty.university.name,
            "Université de Dschang",
        )
        # Les comptes sont conservés, les profils reconstruits sous l'UDS.
        self.assertTrue(User.objects.filter(username="ETU001").exists())
        student = Student.objects.get(user__username="ETU001")
        self.assertEqual(student.faculty.university.name, "Université de Dschang")
        teacher = Teacher.objects.get(user__username="ENS001")
        self.assertEqual(teacher.faculty.university.name, "Université de Dschang")
