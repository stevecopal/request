"""Tests des diffusions temps réel : transaction.on_commit + isolation groupes."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Department, Faculty, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import Course, ProblemType
from tickets.models import Ticket
from tickets.services.status_machine import apply_status


class BroadcastOnCommitTests(TestCase):
    def setUp(self):
        university = make_university()
        faculty = Faculty.objects.create(university=university, name="Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        self.student = Student.objects.create(
            user=User.objects.create_user(username="ETU001", password="x"),
            registration_number="ETU001",
            faculty=faculty,
            department=dept,
        )
        self.teacher = Teacher.objects.create(
            user=User.objects.create_user(username="ENS001", password="x"),
            title="DR",
            faculty=faculty,
            department=dept,
        )
        self.course = Course.objects.create(
            code="INF101", name="Algo", department=dept, primary_instructor=self.teacher
        )
        self.problem = ProblemType.objects.create(name="Note manquante", requires_course=True)

    def _ticket(self, status=Ticket.Status.SENT):
        return Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            description="desc",
            status=status,
        )

    def test_broadcast_emitted_only_after_commit(self):
        """Aucun broadcast pendant la transaction ; émission après commit."""
        ticket = self._ticket()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        # Callback enregistré dans la transaction, exécuté au commit.
        self.assertEqual(len(callbacks), 1)

        with patch("tickets.signals._broadcast") as mock_broadcast:
            ticket2 = self._ticket(Ticket.Status.RECEIVED)
            mock_broadcast.reset_mock()  # ignore le broadcast de création
            with self.captureOnCommitCallbacks(execute=True):
                apply_status(ticket2, Ticket.Status.PROCESSING, actor=self.teacher.user)
            # Deux destinataires : étudiant + enseignant.
            self.assertEqual(mock_broadcast.call_count, 2)
            user_ids = {call.args[0] for call in mock_broadcast.call_args_list}
            self.assertEqual(
                user_ids, {self.student.user_id, self.teacher.user_id}
            )

    def test_payload_contains_ticket_id_and_status(self):
        ticket = self._ticket()
        with patch("tickets.signals._broadcast") as mock_broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        payload = mock_broadcast.call_args_list[0].args[1]
        self.assertEqual(payload["ticket_id"], str(ticket.id))
        self.assertEqual(payload["status"], Ticket.Status.RECEIVED)
        self.assertIn("status_label", payload)


class BroadcastResilienceTests(TestCase):
    """
    Panne du channel layer (Redis en timeout sur le VPS) : jamais bloquante.

    Régression prod : « redis.exceptions.TimeoutError: Timeout reading from
    redis:6379 » survenait à chaque WebSocket et faisait échouer les requêtes
    qui enregistrent un ticket. La diffusion temps réel est best-effort : la
    base reste la source de vérité.
    """

    def setUp(self):
        university = make_university()
        faculty = Faculty.objects.create(university=university, name="Sciences")
        dept = Department.objects.create(faculty=faculty, name="Informatique")
        self.student = Student.objects.create(
            user=User.objects.create_user(username="ETU001", password="x"),
            registration_number="ETU001",
            faculty=faculty,
            department=dept,
        )
        self.teacher = Teacher.objects.create(
            user=User.objects.create_user(username="ENS001", password="x"),
            title="DR",
            faculty=faculty,
            department=dept,
        )
        self.course = Course.objects.create(
            code="INF101", name="Algo", department=dept, primary_instructor=self.teacher
        )
        self.problem = ProblemType.objects.create(name="Note manquante", requires_course=True)

    @staticmethod
    def _broken_layer():
        from unittest.mock import Mock

        layer = Mock()
        layer.group_send.side_effect = TimeoutError("Timeout reading from redis:6379")
        return layer

    def test_broadcast_failure_does_not_raise(self):
        from tickets import signals

        broken = self._broken_layer()
        with patch("tickets.signals.get_channel_layer", return_value=broken):
            signals._broadcast(
                self.student.user_id, {"type": "ticket.status.changed", "ticket_id": "x"}
            )
        broken.group_send.assert_called_once()

    def test_ticket_creation_survives_channel_layer_outage(self):
        """Un ticket est enregistré même quand Redis ne répond plus."""
        with patch("tickets.signals.get_channel_layer", return_value=self._broken_layer()):
            with self.captureOnCommitCallbacks(execute=True):
                ticket = Ticket.objects.create(
                    student=self.student,
                    teacher=self.teacher,
                    course=self.course,
                    problem_type=self.problem,
                    description="desc",
                )
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())

    def test_status_change_survives_channel_layer_outage(self):
        ticket = Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            description="desc",
        )
        with patch("tickets.signals.get_channel_layer", return_value=self._broken_layer()):
            with self.captureOnCommitCallbacks(execute=True):
                apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RECEIVED)
        # Le centre de notifications reste alimenté malgré la panne WS.
        from accounts.models import Notification

        self.assertTrue(Notification.objects.filter(user=self.student.user).exists())
