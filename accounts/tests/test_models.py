"""Tests des modèles accounts : unicité, hiérarchie, onboarding."""

import uuid

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Department, Faculty, Student, Teacher
from accounts.tests.factories import make_university


class FacultyDepartmentTests(TestCase):
    def setUp(self):
        self.university = make_university()

    def test_faculty_name_unique_per_university(self):
        Faculty.objects.create(university=self.university, name="Sciences")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Faculty.objects.create(university=self.university, name="Sciences")

    def test_faculty_same_name_allowed_across_universities(self):
        other = make_university("Autre Université")
        Faculty.objects.create(university=self.university, name="Sciences")
        Faculty.objects.create(university=other, name="Sciences")
        self.assertEqual(Faculty.objects.filter(name="Sciences").count(), 2)

    def test_department_unique_per_faculty(self):
        faculty = Faculty.objects.create(university=self.university, name="Sciences")
        Department.objects.create(faculty=faculty, name="Informatique")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Department.objects.create(faculty=faculty, name="Informatique")

    def test_same_department_name_allowed_across_faculties(self):
        f1 = Faculty.objects.create(university=self.university, name="Sciences")
        f2 = Faculty.objects.create(university=self.university, name="Lettres")
        Department.objects.create(faculty=f1, name="Gestion")
        Department.objects.create(faculty=f2, name="Gestion")
        self.assertEqual(Department.objects.filter(name="Gestion").count(), 2)

    def test_university_is_derived_from_faculty(self):
        faculty = Faculty.objects.create(university=self.university, name="Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        student = Student.objects.create(
            user=User.objects.create_user(username="ETU001", password="x"),
            registration_number="ETU001",
            faculty=faculty,
            department=dept,
        )
        self.assertEqual(student.university, self.university)

    def test_uuid_primary_key(self):
        faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.assertIsInstance(faculty.id, uuid.UUID)


class StudentOnboardingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="x")

    def test_is_onboarded_false_when_nullable_fields_empty(self):
        student = Student.objects.create(user=self.user, registration_number="ETU001")
        self.assertFalse(student.is_onboarded)

    def test_is_onboarded_true_after_assignment(self):
        faculty = Faculty.objects.create(university=make_university(), name="Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        student = Student.objects.create(
            user=self.user,
            registration_number="ETU001",
            faculty=faculty,
            department=dept,
        )
        self.assertTrue(student.is_onboarded)

    def test_registration_number_unique(self):
        Student.objects.create(user=self.user, registration_number="ETU001")
        other = User.objects.create_user(username="ETU999", password="x")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Student.objects.create(user=other, registration_number="ETU001")


class TeacherTests(TestCase):
    def test_full_name_includes_title(self):
        user = User.objects.create_user(
            username="ENS001", first_name="Paul", last_name="Ndongo"
        )
        faculty = Faculty.objects.create(university=make_university(), name="Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        teacher = Teacher.objects.create(
            user=user, title="DR", faculty=faculty, department=dept
        )
        self.assertIn("Ndongo", teacher.full_name)
        self.assertIn("Dr.", teacher.full_name)
