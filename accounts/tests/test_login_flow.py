"""Tests du parcours de connexion — séparation affichage / authentification.

Couvre la mission anti-405 :
  Test 1 : GET /login/ -> 200, contient login-form + route POST correcte.
  Test 2 : GET /accounts/login/ -> 405 sans session authentifiée.
  Test 3 : POST valide -> JSON success + session ; POST invalide -> erreur JSON.
  Test 4 : CSRF conforme (client avec contrôle CSRF : POST sans jeton -> 403).
  Test 5 : 5 échecs -> blocage 5 min (429), succès réinitialise les compteurs.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Student


class LoginDisplayTests(TestCase):
    """Test 1 : affichage du formulaire."""

    def test_login_fragment_returns_form_with_correct_action(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("login-form", html)
        # Le formulaire doit pointer vers l'endpoint JSON (POST uniquement).
        self.assertIn('action="/accounts/login/"', html)
        self.assertIn('data-login-url="/accounts/login/"', html)
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn('method="post"', html.lower())

    def test_login_page_url_name_resolves_to_fragment(self):
        self.assertEqual(reverse("accounts:login_page"), "/login/")
        self.assertEqual(reverse("accounts:login"), "/accounts/login/")


class LoginMethodTests(TestCase):
    """Test 2 : méthode incorrecte sur l'endpoint JSON."""

    def test_get_login_returns_405_without_session(self):
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 405)
        # Aucune session authentifiée ne doit être créée par ce GET.
        self.assertNotIn("_auth_user_id", self.client.session)


class LoginAuthenticationTests(TestCase):
    """Test 3 : authentification."""

    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="Secret123!")
        Student.objects.create(user=self.user, registration_number="ETU001")

    def test_post_valid_credentials_authenticates(self):
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["next"], reverse("accounts:dashboard"))
        # Session correctement établie.
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_post_invalid_credentials_returns_json_error(self):
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "faux"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["status"], "error")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_is_rejected(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)


class LoginCsrfTests(TestCase):
    """Test 4 : protection CSRF conforme à la configuration Django."""

    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="Secret123!")
        Student.objects.create(user=self.user, registration_number="ETU001")

    def test_post_without_csrf_token_is_forbidden_when_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", csrf_client.session)


class LoginRateLimitTests(TestCase):
    """Test 5 : limitation des tentatives (5 échecs -> blocage 5 minutes)."""

    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="Secret123!")
        Student.objects.create(user=self.user, registration_number="ETU001")

    def test_blocked_after_five_failures(self):
        for _ in range(5):
            response = self.client.post(
                "/accounts/login/", {"matricule": "ETU001", "password": "faux"}
            )
        self.assertIn(response.status_code, (401, 429))
        # La 6e tentative (même avec de bons identifiants) est bloquée.
        blocked = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["status"], "error")

    def test_success_resets_counters(self):
        for _ in range(3):
            self.client.post(
                "/accounts/login/", {"matricule": "ETU001", "password": "faux"}
            )
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertNotIn("login_attempts", session)
        self.assertNotIn("login_lock_until", session)
