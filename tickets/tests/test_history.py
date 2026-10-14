"""Tests de l'historique horodaté des tickets (TicketStatusHistory)."""

import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Department, Faculty, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import AttachmentConfig, Course, ProblemType
from tickets.models import Ticket, TicketStatusHistory
from tickets.services.status_machine import apply_status
from tickets.services.ticket_creator import create_student_ticket


class TicketHistoryTests(TestCase):
    def setUp(self):
        self.university = make_university()
        faculty = Faculty.objects.create(university=self.university, name="Sciences")
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
        self.config = AttachmentConfig.objects.create(
            problem_type=self.problem, label="Résultat du portail", is_required=True
        )

    def _ticket(self, status=Ticket.Status.PROCESSING):
        return Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            description="desc",
            status=status,
        )

    def test_creation_records_history_entry(self):
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            ticket = create_student_ticket(
                student_profile=self.student,
                problem_type_id=self.problem.id,
                description="Ma note manque.",
                uploaded_files_dict={
                    str(self.config.id): SimpleUploadedFile(
                        "p.pdf", b"%PDF-1.4", content_type="application/pdf"
                    )
                },
                course_id=self.course.id,
            )
        entry = ticket.status_history.get()
        self.assertIsNone(entry.from_status)
        self.assertEqual(entry.to_status, Ticket.Status.SENT)
        self.assertEqual(entry.actor, self.student.user)
        self.assertEqual(entry.actor_role, TicketStatusHistory.ActorRole.STUDENT)
        self.assertIsNotNone(entry.created_at)

    def test_transition_records_history_with_actor(self):
        ticket = self._ticket(Ticket.Status.SENT)
        apply_status(
            ticket,
            Ticket.Status.RECEIVED,
            actor=self.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
        )
        entry = ticket.status_history.get()
        self.assertEqual(entry.from_status, Ticket.Status.SENT)
        self.assertEqual(entry.to_status, Ticket.Status.RECEIVED)
        self.assertEqual(entry.actor, self.teacher.user)

    def test_rejection_journals_reason_in_note(self):
        ticket = self._ticket()
        apply_status(
            ticket,
            Ticket.Status.REJECTED,
            reason="Pièce illisible",
            actor=self.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            note="Pièce illisible",
        )
        entry = ticket.status_history.latest("created_at")
        self.assertEqual(entry.to_status, Ticket.Status.REJECTED)
        self.assertIn("Pièce illisible", entry.note)

    def test_full_lifecycle_keeps_chronological_history(self):
        ticket = self._ticket(Ticket.Status.SENT)
        apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        apply_status(ticket, Ticket.Status.PROCESSING, actor=self.teacher.user)
        apply_status(ticket, Ticket.Status.RESOLVED, actor=self.teacher.user)
        history = list(ticket.status_history.order_by("created_at"))
        self.assertEqual(
            [h.to_status for h in history],
            [
                Ticket.Status.RECEIVED,
                Ticket.Status.PROCESSING,
                Ticket.Status.RESOLVED,
            ],
        )
        # Horodatage chronologique non décroissant.
        timestamps = [h.created_at for h in history]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_history_exposed_in_ticket_detail(self):
        from django.test import Client

        ticket = self._ticket(Ticket.Status.SENT)
        apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        client = Client()
        client.force_login(self.teacher.user)
        response = client.get(f"/tickets/{ticket.id}/detail/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique")
