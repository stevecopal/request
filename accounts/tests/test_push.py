"""Tests des endpoints Web Push : abonnement, désabonnement, permissions."""

import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import PushSubscription, Student

SUBSCRIBE = "/accounts/ajax/push/subscribe/"
UNSUBSCRIBE = "/accounts/ajax/push/unsubscribe/"


def sample_subscription(endpoint="https://push.example/abc123"):
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "BNc", "auth": "AHa"},
    }


@override_settings(VAPID_PRIVATE_KEY="8SiQaNsaUO5jij5cD8hGw9EG50Si13ZDevfhmOYa5Ek",
                   VAPID_PUBLIC_KEY="BL_UD76imP5WgALOQSO7ew9aBZHwIiO_I_E-fPBMZoMSiYFGG5bdacgfb2yVWI96MKPhREyBamhJeHBdFiSWKA4")
class PushEndpointsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ETU001", password="x")
        Student.objects.create(user=self.user, registration_number="ETU001")
        self.other = User.objects.create_user(username="ETU002", password="x")
        Student.objects.create(user=self.other, registration_number="ETU002")
        self.client.force_login(self.user)

    def _post(self, url, subscription):
        return self.client.post(
            url,
            data=json.dumps({"subscription": subscription}),
            content_type="application/json",
        )

    def test_subscribe_creates_subscription_for_current_user(self):
        response = self._post(SUBSCRIBE, sample_subscription())
        self.assertEqual(response.status_code, 200)
        sub = PushSubscription.objects.get(endpoint="https://push.example/abc123")
        self.assertEqual(sub.user, self.user)

    def test_subscribe_requires_authentication(self):
        self.client.logout()
        response = self._post(SUBSCRIBE, sample_subscription())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_subscribe_rejects_invalid_payload(self):
        response = self.client.post(
            SUBSCRIBE, data=json.dumps({}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_unsubscribe_only_removes_own_subscription(self):
        PushSubscription.objects.create(
            user=self.user, endpoint="https://push.example/mine", p256dh="a", auth="b"
        )
        PushSubscription.objects.create(
            user=self.other, endpoint="https://push.example/theirs", p256dh="a", auth="b"
        )
        response = self._post(
            UNSUBSCRIBE, {"endpoint": "https://push.example/theirs"}
        )
        self.assertEqual(response.status_code, 200)
        # L'abonnement d'un autre utilisateur n'est jamais supprimé (IDOR).
        self.assertTrue(
            PushSubscription.objects.filter(endpoint="https://push.example/theirs").exists()
        )
        # Le sien l'est.
        self._post(UNSUBSCRIBE, {"endpoint": "https://push.example/mine"})
        self.assertFalse(
            PushSubscription.objects.filter(endpoint="https://push.example/mine").exists()
        )

    def test_subscribe_disabled_without_vapid_keys(self):
        with override_settings(VAPID_PRIVATE_KEY="", VAPID_PUBLIC_KEY=""):
            response = self._post(SUBSCRIBE, sample_subscription("https://push.example/x"))
        self.assertEqual(response.status_code, 503)
