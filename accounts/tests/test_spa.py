"""Coque SPA : inlining du fragment initial (perf) et garde-fous XHR.

Un accès document (F5, lien partagé) à une vue-fragment doit renvoyer la
coque avec le fragment déjà inliné (`data-fragment-inlined="1"`) — aucun
second fetch au chargement. Les requêtes XHR gardent le fragment nu, et
les erreurs d'autorisation restent du JSON (401) pour le repli JS.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Student


class ShellInlineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="x")
        Student.objects.create(user=self.user, registration_number="ETU001")
        self.client.force_login(self.user)

    def test_dashboard_shell_inlines_role_fragment(self):
        """L'entrée /dashboard/ inline le fragment du rôle : zéro fetch initial."""
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="spa-viewport"')
        self.assertContains(response, 'data-fragment-inlined="1"')
        self.assertContains(response, 'aria-busy="false"')

    def test_direct_fragment_url_inlines_html_in_shell(self):
        """Accès direct à une vue-fragment : coque + fragment en ligne."""
        response = self.client.get("/tickets/accueil/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="spa-viewport"')
        self.assertContains(response, 'data-fragment-inlined="1"')

    def test_xhr_fragment_request_returns_bare_fragment(self):
        """Le fetch du client reçoit le fragment nu, sans coque."""
        response = self.client.get(
            "/tickets/accueil/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="spa-viewport"')
        self.assertNotContains(response, 'data-fragment-inlined')

    def test_unauthenticated_direct_fragment_returns_401_json(self):
        """Session expirée : 401 JSON — app_spa.js bascule sur /login/."""
        self.client.logout()
        response = self.client.get("/tickets/accueil/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["status"], "error")
