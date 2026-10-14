"""
Tests de sécurité HTTP — UnivReq.

Règle d'architecture : GET = lecture seule ; toute écriture / authentification
passe par POST. Une requête GET sur un point d'écriture doit répondre 405 et
ne jamais exposer d'identifiants dans l'URL.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Student

WRITE_ENDPOINTS = [
    "/accounts/login/",
    "/accounts/logout/",
    "/accounts/ajax/onboarding/",
    "/tickets/ajax/create/",
    "/tickets/ajax/status/",
    "/scolarite/admin/import/upload/",
    "/scolarite/admin/accounts/create/",
]


class HttpMethodEnforcementTests(TestCase):
    def test_get_not_allowed_on_write_endpoints(self):
        for endpoint in WRITE_ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 405, endpoint)

    def test_get_read_endpoints_remain_available(self):
        # Les lectures sûres restent des GET.
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/login/").status_code, 200)


class LoginFormSecurityTests(TestCase):
    def test_login_form_declares_post_and_csrf(self):
        html = self.client.get("/login/").content.decode()
        # Sans JS, le navigateur doit envoyer en POST (jamais en query string).
        self.assertIn('method="post"', html.lower())
        self.assertIn('action="/accounts/login/"', html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_write_forms_declare_post(self):
        endpoints = [
            "/scolarite/admin/import/",
            "/scolarite/admin/accounts/new/",
        ]
        user = User.objects.create_superuser(username="ADMIN001", password="x", email="a@b.c")
        self.client.force_login(user)
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                html = self.client.get(endpoint).content.decode().lower()
                self.assertIn('method="post"', html)

    def test_credential_is_not_reflected_in_url(self):
        """Le matricule ne doit jamais apparaître dans l'URL après soumission."""
        User.objects.create_user(username="ETU001", password="Secret123!")
        Student.objects.create(
            user=User.objects.get(username="ETU001"), registration_number="ETU001"
        )
        response = self.client.post(
            "/accounts/login/", {"matricule": "ETU001", "password": "Secret123!"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ETU001", response.request["PATH_INFO"])
        self.assertNotIn("password", response.request["QUERY_STRING"])
