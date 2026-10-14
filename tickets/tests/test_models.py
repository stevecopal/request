"""Tests du modèle Ticket : statuts, contrainte de motif, timestamps."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Department, Faculty, Student, Teacher
from core_scolarite.models import Course, ProblemType
from tickets.models import Ticket


class TicketModelTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Sciences")
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
        self.course = Course.objects.create(code="INF101", name="Algo", department=dept)
        self.problem = ProblemType.objects.create(name="Note manquante")

    def _ticket(self, **kwargs):
        defaults = {
            "student": self.student,
            "teacher": self.teacher,
            "course": self.course,
            "problem_type": self.problem,
            "description": "desc",
        }
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_default_status_is_sent(self):
        self.assertEqual(self._ticket().status, Ticket.Status.SENT)

    def test_status_choices_complete(self):
        values = {choice.value for choice in Ticket.Status}
        self.assertEqual(
            values, {"SENT", "RECEIVED", "PROCESSING", "RESOLVED", "REJECTED"}
        )

    def test_rejected_requires_reason_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._ticket(status=Ticket.Status.REJECTED, rejection_reason="")

    def test_rejected_with_reason_allowed(self):
        ticket = self._ticket(
            status=Ticket.Status.REJECTED, rejection_reason="Pièce manquante"
        )
        self.assertEqual(ticket.status, Ticket.Status.REJECTED)

    def test_status_label_is_french(self):
        self.assertEqual(self._ticket(status=Ticket.Status.RECEIVED).status_label, "Reçu")

    def test_is_open_reflects_terminal_states(self):
        self.assertTrue(self._ticket(status=Ticket.Status.PROCESSING).is_open)
        self.assertFalse(self._ticket(status=Ticket.Status.RESOLVED).is_open)
