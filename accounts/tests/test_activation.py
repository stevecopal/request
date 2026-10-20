"""Tests du parcours « première connexion » et de la réinitialisation.

Couvre le brief §3 : matricule + e-mail → lien temporaire à usage unique
envoyé par e-mail → définition du mot de passe → activation → connexion par
matricule **ou** e-mail.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccessLink, Department, Faculty, Student
from accounts.services import access_links
from accounts.tests.factories import make_university

PASSWORD = "Secret123!"


class ActivationFlowTests(TestCase):
    def setUp(self):
        cache.clear()  # compteur de tentatives partagé (throttle)
        self.university = make_university()
        faculty = Faculty.objects.create(
            university=self.university, name="Sciences", code="SCI"
        )
        department = Department.objects.create(faculty=faculty, name="Informatique")
        self.user = User.objects.create_user(
            username="CM-UDS-26SCI0001",
            first_name="Jean",
            last_name="Kouam",
            email="jean.kouam@univ-dschang.org",
            is_active=False,
        )
        Student.objects.create(
            user=self.user, registration_number=self.user.username,
            faculty=faculty, department=department,
        )

    def _request_link(self, matricule=None, email=None, url=None):
        return self.client.post(
            url or reverse("accounts:activation_request"),
            {
                "matricule": matricule or self.user.username,
                "email": email or self.user.email,
            },
        )

    def test_valid_request_sends_email_with_one_time_link(self):
        response = self._request_link()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn(self.user.email, message.to)
        body = message.body
        self.assertIn("/activation/", body)
        # Le jeton du lien fonctionne réellement.
        token = body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        self.assertTrue(access_links.resolve(token, AccessLink.Purpose.ACTIVATION))

    def test_email_link_is_absolute_and_clickable(self):
        """Le lien du mail est absolu (origine canonique SITE_URL), donc cliquable."""
        from django.test import override_settings

        with override_settings(SITE_URL="https://portail.univ-dschang.org"):
            self._request_link()
        body = mail.outbox[0].body
        self.assertIn("https://portail.univ-dschang.org/activation/", body)
        # Jamais de chemin nu « /activation/… » dans le corps du mail.
        for line in body.splitlines():
            if "/activation/" in line:
                self.assertTrue(line.startswith("https://"), line)

    def test_wrong_email_sends_nothing_but_generic_message(self):
        response = self._request_link(email="inconnu@exemple.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        # Message identique à celui d'un compte existant : aucune divulgation.
        self.assertContains(response, "Si le matricule et l")

    def test_unknown_matricule_sends_nothing(self):
        response = self._request_link(matricule="CM-UDS-26SCI9999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_activation_sets_password_and_activates_account(self):
        self._request_link()
        token = mail.outbox[0].body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        url = reverse("accounts:activation_confirm", args=[token])

        response = self.client.post(
            url, {"password1": PASSWORD, "password2": PASSWORD}
        )
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_login_with_matricule_then_with_email(self):
        self._request_link()
        token = mail.outbox[0].body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        self.client.post(
            reverse("accounts:activation_confirm", args=[token]),
            {"password1": PASSWORD, "password2": PASSWORD},
        )
        self.client.logout()

        response = self.client.post(
            reverse("accounts:login"), {"matricule": self.user.username, "password": PASSWORD}
        )
        self.assertEqual(response.json()["status"], "success")
        self.client.logout()

        response = self.client.post(
            reverse("accounts:login"), {"matricule": self.user.email, "password": PASSWORD}
        )
        self.assertEqual(response.json()["status"], "success")

    def test_link_is_single_use(self):
        self._request_link()
        token = mail.outbox[0].body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        url = reverse("accounts:activation_confirm", args=[token])
        self.client.post(url, {"password1": PASSWORD, "password2": PASSWORD})

        # Second usage du même lien : refusé, le mot de passe reste inchangé.
        response = self.client.post(
            url, {"password1": "Other123!", "password2": "Other123!"}
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertFalse(self.user.check_password("Other123!"))

    def test_expired_link_rejected(self):
        self._request_link()
        token = mail.outbox[0].body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        AccessLink.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        response = self.client.post(
            reverse("accounts:activation_confirm", args=[token]),
            {"password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_weak_password_rejected(self):
        self._request_link()
        token = mail.outbox[0].body.split("/activation/")[1].split("\n")[0].strip().rstrip("/")
        response = self.client.post(
            reverse("accounts:activation_confirm", args=[token]),
            {"password1": "123", "password2": "123"},
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("123"))

    def test_admin_can_issue_link_when_email_unreachable(self):
        """Procédure contrôlée : l'admin génère le lien, affiché une seule fois."""
        admin = User.objects.create_superuser(username="ADMIN001", password="x")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("core_scolarite:admin_users_credentials", args=[]) + f"?pk={self.user.pk}",
            {"mode": "link"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("/activation/", payload["link"])
        link = AccessLink.objects.get(user=self.user)
        self.assertEqual(link.created_by, admin)

        # Le lien généré fonctionne.
        token = payload["link"].split("/activation/")[1].split("/")[0]
        confirm = self.client.post(
            reverse("accounts:activation_confirm", args=[token]),
            {"password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(confirm.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="CM-UDS-26SCI0002", email="reset@univ-dschang.org", password="Old123!"
        )

    def test_reset_link_replaces_password(self):
        response = self.client.post(
            reverse("accounts:reset_request"),
            {"matricule": self.user.username, "email": self.user.email},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        token = mail.outbox[0].body.split("/reinitialisation/")[1].split("\n")[0].strip().rstrip("/")

        response = self.client.post(
            reverse("accounts:password_reset_confirm", args=[token]),
            {"password1": "NewSecret1!", "password2": "NewSecret1!"},
        )
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("Old123!"))
        self.assertTrue(self.user.check_password("NewSecret1!"))

    def test_reset_requires_matching_email(self):
        self.client.post(
            reverse("accounts:reset_request"),
            {"matricule": self.user.username, "email": "autre@univ-dschang.org"},
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_is_single_use(self):
        self.client.post(
            reverse("accounts:reset_request"),
            {"matricule": self.user.username, "email": self.user.email},
        )
        token = mail.outbox[0].body.split("/reinitialisation/")[1].split("\n")[0].strip().rstrip("/")
        url = reverse("accounts:password_reset_confirm", args=[token])
        self.client.post(url, {"password1": "NewSecret1!", "password2": "NewSecret1!"})
        response = self.client.post(
            url, {"password1": "Again123!", "password2": "Again123!"}
        )
        self.assertEqual(response.status_code, 400)


class AccessRequestRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="CM-UDS-26SCI0003", email="rate@univ-dschang.org"
        )

    def test_repeated_requests_are_throttled(self):
        url = reverse("accounts:activation_request")
        for _ in range(5):
            self.client.post(url, {"matricule": self.user.username, "email": self.user.email})
        response = self.client.post(
            url, {"matricule": self.user.username, "email": self.user.email}
        )
        self.assertEqual(response.status_code, 429)
