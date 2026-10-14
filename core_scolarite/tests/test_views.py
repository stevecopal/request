"""Tests des vues core_scolarite : form-config et import admin."""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from accounts.models import Department, Faculty, Student, Teacher
from core_scolarite.models import AttachmentConfig, Course, ProblemType


def make_student(username, faculty, department):
    user = User.objects.create_user(username=username, password="x")
    return Student.objects.create(
        user=user, registration_number=username, faculty=faculty, department=department
    )


class FormConfigTests(TestCase):
    def setUp(self):
        self.faculty = Faculty.objects.create(name="Sciences")
        self.info = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.math = Department.objects.create(faculty=self.faculty, name="Mathématiques")
        self.student = make_student("ETU001", self.faculty, self.info)

        teacher_user = User.objects.create_user(
            username="ENS001", first_name="Paul", last_name="Ndongo"
        )
        self.teacher = Teacher.objects.create(
            user=teacher_user, title="DR", faculty=self.faculty, department=self.info
        )
        Course.objects.create(
            code="INF101", name="Algo", department=self.info, primary_instructor=self.teacher
        )
        Course.objects.create(code="MAT210", name="Algèbre", department=self.math)

        self.problem = ProblemType.objects.create(name="Note manquante", requires_course=True)
        AttachmentConfig.objects.create(
            problem_type=self.problem, label="Résultat du portail", is_required=True
        )
        self.client.force_login(self.student.user)

    def test_courses_filtered_by_student_department(self):
        response = self.client.get(
            f"/scolarite/ajax/form-config/?problem_type_id={self.problem.id}"
        )
        self.assertEqual(response.status_code, 200)
        codes = [c["code"] for c in response.json()["courses"]]
        self.assertEqual(codes, ["INF101"])

    def test_attachments_returned(self):
        response = self.client.get(
            f"/scolarite/ajax/form-config/?problem_type_id={self.problem.id}"
        )
        attachments = response.json()["attachments"]
        self.assertEqual(attachments[0]["label"], "Résultat du portail")
        self.assertTrue(attachments[0]["is_required"])

    def test_requires_course_false_returns_no_courses(self):
        problem = ProblemType.objects.create(name="Attestation", requires_course=False)
        response = self.client.get(f"/scolarite/ajax/form-config/?problem_type_id={problem.id}")
        self.assertEqual(response.json()["courses"], [])

    def test_not_onboarded_returns_onboarding_required(self):
        plain = User.objects.create_user(username="ETUX", password="x")
        Student.objects.create(user=plain, registration_number="ETUX")
        self.client.force_login(plain)
        response = self.client.get(
            f"/scolarite/ajax/form-config/?problem_type_id={self.problem.id}"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "onboarding_required")

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(
            f"/scolarite/ajax/form-config/?problem_type_id={self.problem.id}"
        )
        self.assertEqual(response.status_code, 401)


class AdminImportTests(TestCase):
    def setUp(self):
        Faculty.objects.create(name="Sciences")
        self.superuser = User.objects.create_superuser(
            username="ADMIN001", password="x", email="a@b.c"
        )
        self.plain = User.objects.create_user(username="ETU001", password="x")

    def _upload(self):
        content = (
            "MATRICULE,NOM,PRENOM,EMAIL,FACULTE,DEPARTEMENT\n"
            "M1,Doe,John,john@univ.cm,Sciences,Informatique"
        )
        return SimpleUploadedFile("f.csv", content.encode(), content_type="text/csv")

    def test_non_superuser_forbidden(self):
        self.client.force_login(self.plain)
        response = self.client.post(
            "/scolarite/admin/import/upload/",
            {"file": self._upload(), "entity": "students"},
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_upload_missing_department_reports_errors(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            "/scolarite/admin/import/upload/",
            {"file": self._upload(), "entity": "students"},
        )
        # Le département "Informatique" n'existe pas → 400 avec détail par ligne.
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["errors"])

    def test_superuser_upload_success(self):
        faculty = Faculty.objects.get(name="Sciences")
        Department.objects.create(faculty=faculty, name="Informatique")
        self.client.force_login(self.superuser)
        response = self.client.post(
            "/scolarite/admin/import/upload/",
            {"file": self._upload(), "entity": "students"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported_count"], 1)
