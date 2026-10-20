"""Tests des matricules officiels — génération sans collision et validation."""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Faculty, Student
from accounts.services import matricules
from accounts.tests.factories import make_university


class MatriculeGenerationTests(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(
            university=self.university, name="Sciences", code="SCI"
        )

    def _create_student(self, matricule: str):
        user = User.objects.create_user(username=matricule, password="x")
        return Student.objects.create(user=user, registration_number=matricule)

    def test_generated_format_is_official(self):
        matricule = matricules.generate(self.faculty, "students")
        year = f"{matricules.registration_year() % 100:02d}"
        self.assertRegex(matricule, rf"^CM-UDS-{year}SCI\d{{4}}$")

    def test_sequence_increments_without_collision(self):
        first = matricules.generate(self.faculty, "students")
        self._create_student(first)
        second = matricules.generate(self.faculty, "students")
        self._create_student(second)
        self.assertNotEqual(first, second)
        self.assertEqual(int(second[-4:]), int(first[-4:]) + 1)

    def test_sequence_resumes_after_existing_accounts(self):
        year = f"{matricules.registration_year() % 100:02d}"
        self._create_student(f"CM-UDS-{year}SCI0007")
        matricule = matricules.generate(self.faculty, "students")
        self.assertEqual(matricule, f"CM-UDS-{year}SCI0008")

    def test_teacher_segment_is_defined_separately(self):
        matricule = matricules.generate(self.faculty, "teachers")
        self.assertIn("ENS", matricule)
        self.assertNotIn("SCI", matricule)


class MatriculeValidationTests(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(
            university=self.university, name="Sciences", code="SCI"
        )
        self.lettres = Faculty.objects.create(
            university=self.university, name="Lettres", code="LET"
        )

    def test_valid_student_matricule_accepted(self):
        normalized = matricules.validate(
            "cm-uds-26sci0001",
            entity="students",
            university=self.university,
            faculty=self.faculty,
        )
        self.assertEqual(normalized, "CM-UDS-26SCI0001")

    def test_legacy_format_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            matricules.validate(
                "CM_UDS_26SCI0001",
                entity="students",
                university=self.university,
                faculty=self.faculty,
            )
        self.assertIn("MATRICULE", str(ctx.exception))

    def test_missing_matricule_rejected(self):
        with self.assertRaises(ValueError):
            matricules.validate(
                "", entity="students", university=self.university, faculty=self.faculty
            )

    def test_wrong_faculty_code_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            matricules.validate(
                "CM-UDS-26LET0001",
                entity="students",
                university=self.university,
                faculty=self.faculty,
            )
        self.assertIn("incohérent", str(ctx.exception))

    def test_wrong_country_rejected(self):
        with self.assertRaises(ValueError):
            matricules.validate(
                "TG-UDS-26SCI0001",
                entity="students",
                university=self.university,
                faculty=self.faculty,
            )

    def test_future_year_rejected(self):
        year = (matricules.registration_year() + 1) % 100
        with self.assertRaises(ValueError) as ctx:
            matricules.validate(
                f"CM-UDS-{year}SCI0001",
                entity="students",
                university=self.university,
                faculty=self.faculty,
            )
        self.assertIn("année", str(ctx.exception).lower())

    def test_teacher_segment_required(self):
        matricules.validate(
            "CM-UDS-26ENS0001",
            entity="teachers",
            university=self.university,
            faculty=self.faculty,
        )
        with self.assertRaises(ValueError):
            matricules.validate(
                "CM-UDS-26SCI0001",
                entity="teachers",
                university=self.university,
                faculty=self.faculty,
            )

    def test_faculty_without_code_blocks_generation(self):
        sans_code = Faculty.objects.create(
            university=self.university, name="Médecine", code=""
        )
        with self.assertRaises(ValueError):
            matricules.generate(sans_code, "students")


class FacultyCodeTests(TestCase):
    def test_code_is_uppercased_on_save(self):
        university = make_university()
        faculty = Faculty.objects.create(university=university, name="Droit", code="dro")
        self.assertEqual(faculty.code, "DRO")

    def test_duplicate_code_in_same_university_rejected(self):
        from django.db import IntegrityError

        university = make_university()
        Faculty.objects.create(university=university, name="Sciences", code="SCI")
        with self.assertRaises(IntegrityError):
            Faculty.objects.create(university=university, name="Autre", code="SCI")

    def test_code_unique_per_university_only(self):
        other = make_university(name="Autre Université")
        Faculty.objects.create(university=make_university(), name="Sciences", code="SCI")
        Faculty.objects.create(university=other, name="Sciences", code="SCI")
