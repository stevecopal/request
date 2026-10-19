"""Tests des vues accounts : connexion, cascade, onboarding, sécurité."""

import json

from django.contrib.auth.models import User
from django.template.loader import render_to_string
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
        self.assertEqual(response.json()["user_type"], "student")

    def test_login_invalid_credentials(self):
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 401)
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


class LandingDownloadButtonTests(TestCase):
    """Bouton « Télécharger l’application » de la navigation publique."""

    def test_landing_shows_install_button_desktop_and_mobile(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # Desktop (icône + libellé, ≥ lg) + mobile (icône seule, < lg).
        self.assertEqual(html.count("data-install-app"), 2)
        self.assertIn("Télécharger l’application", html)
        self.assertIn('aria-label="Télécharger l’application"', html)
        self.assertIn("pwa_install.js", html)
        # Version mobile : positionnée avant la bascule du menu déroulant.
        self.assertLess(html.rfind("data-install-app"), html.find("data-nav-toggle"))

    def test_mobile_install_button_restricted_to_anonymous_visitors(self):
        user = User.objects.create_user(username="ENS001", password="x")
        html = render_to_string("components/public_navbar.html", {"user": user})
        # Connecté : seul le bouton desktop subsiste (mobile masqué).
        self.assertEqual(html.count("data-install-app"), 1)


class PwaInstallTests(TestCase):
    """Configuration PWA : manifest installable + service worker + textes du flux."""

    def test_manifest_served_at_root_with_official_mime_type(self):
        response = self.client.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        manifest = json.loads(b"".join(response.streaming_content))

        # Critères d'installabilité Chrome/Edge : start_url en 200 direct
        # (une redirection 302 empêchait l'émission de
        # `beforeinstallprompt`), scope racine, affichage standalone.
        self.assertEqual(manifest["id"], "/")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

        # Le start_url répond bien 200 sans redirection pour un anonyme…
        start = self.client.get(manifest["start_url"])
        self.assertEqual(start.status_code, 200)

    def test_landing_links_manifest_and_registers_service_worker(self):
        html = self.client.get("/").content.decode()
        self.assertIn('rel="manifest"', html)
        self.assertIn("/manifest.json", html)
        # Enregistrement immédiat du SW (fin du body) + SW servi à la racine.
        self.assertIn("navigator.serviceWorker", html)
        self.assertIn("/service-worker.js", html)

        sw = self.client.get("/service-worker.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw["Service-Worker-Allowed"], "/")

    def test_install_messages_carried_by_navbar_root(self):
        html = self.client.get("/").content.decode()
        # pwa_install.js lit les textes i18n sur [data-public-navbar].
        for attr in (
            "data-install-waiting=",
            "data-install-done=",
            "data-install-https=",
            "data-install-fallback=",
            "data-install-fallback-ios=",
        ):
            self.assertIn(attr, html)
