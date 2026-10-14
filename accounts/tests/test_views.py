"""Tests des vues accounts : connexion, cascade, onboarding, sécurité."""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Department, Faculty, Student
from accounts.tests.factories import make_university


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="Secret123!")
        Student.objects.create(user=self.user, registration_number="ETU001")

    def test_login_success_returns_json_and_role(self):
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["role"], "student")

    def test_login_invalid_credentials(self):
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")

    def test_login_rate_limited_after_five_attempts(self):
        for _ in range(5):
            self.client.post(
                "/accounts/login/", {"matricule": "ETU001", "password": "wrong"}
            )
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 429)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)
        self.assertEqual(self.client.post("/accounts/logout/").status_code, 200)


class DepartmentCascadeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="x")
        Student.objects.create(user=self.user, registration_number="ETU001")
        university = make_university()
        self.faculty = Faculty.objects.create(university=university, name="Sciences")
        self.other = Faculty.objects.create(university=university, name="Lettres")
        Department.objects.create(faculty=self.faculty, name="Informatique")
        Department.objects.create(faculty=self.other, name="Histoire")

    def test_departments_filtered_by_faculty(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/accounts/ajax/departments/?faculty={self.faculty.id}")
        self.assertEqual(response.status_code, 200)
        names = [d["name"] for d in response.json()["departments"]]
        self.assertEqual(names, ["Informatique"])

    def test_departments_requires_authentication(self):
        response = self.client.get(f"/accounts/ajax/departments/?faculty={self.faculty.id}")
        self.assertEqual(response.status_code, 401)


class OnboardingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="x")
        self.student = Student.objects.create(
            user=self.user, registration_number="ETU001"
        )
        self.university = make_university()
        self.faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.department = Department.objects.create(
            faculty=self.faculty, name="Informatique"
        )
        self.client.force_login(self.user)

    def test_onboarding_updates_only_current_student(self):
        response = self.client.post(
            "/accounts/ajax/onboarding/",
            {"faculty": str(self.faculty.id), "department": str(self.department.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_onboarded)

    def test_department_must_belong_to_faculty(self):
        other = Faculty.objects.create(university=self.university, name="Lettres")
        response = self.client.post(
            "/accounts/ajax/onboarding/",
            {"faculty": str(other.id), "department": str(self.department.id)},
        )
        self.assertEqual(response.status_code, 400)

    def test_onboarding_ignores_client_supplied_student_id(self):
        # Aucun champ student_id/registration_number ne doit être lu (IDOR).
        response = self.client.post(
            "/accounts/ajax/onboarding/",
            {
                "faculty": str(self.faculty.id),
                "department": str(self.department.id),
                "student_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.department_id, self.department.id)


class DashboardRoutingTests(TestCase):
    def test_anonymous_redirected_from_dashboard(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
