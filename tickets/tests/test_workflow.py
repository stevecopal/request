"""Tests du cycle de vie des tickets : création, statuts, permissions (IDOR)."""

import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Department, Faculty, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import AttachmentConfig, Course, ProblemType
from tickets.models import Ticket
from tickets.services.status_machine import StatusTransitionError, apply_status
from tickets.services.ticket_creator import TicketCreationError, create_student_ticket


class BaseWorkflowTests(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.info = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.math = Department.objects.create(faculty=self.faculty, name="Mathématiques")

        self.student = self._student("ETU001", self.info)
        self.other_student = self._student("ETU002", self.info, faculty=None)
        self.teacher = self._teacher("ENS001", self.info)
        self.other_teacher = self._teacher("ENS002", self.math)

        self.course = Course.objects.create(
            code="INF101",
            name="Algo",
            department=self.info,
            primary_instructor=self.teacher,
        )
        self.foreign_course = Course.objects.create(
            code="MAT210", name="Algèbre", department=self.math
        )

        self.problem = ProblemType.objects.create(name="Note manquante", requires_course=True)
        self.config = AttachmentConfig.objects.create(
            problem_type=self.problem, label="Résultat du portail", is_required=True
        )

    def _student(self, username, department, faculty=None):
        faculty = faculty or department.faculty
        return Student.objects.create(
            user=User.objects.create_user(username=username, password="x"),
            registration_number=username,
            faculty=faculty,
            department=department,
        )

    def _teacher(self, username, department):
        return Teacher.objects.create(
            user=User.objects.create_user(username=username, password="x"),
            title="DR",
            faculty=department.faculty,
            department=department,
        )

    def _file(self):
        return SimpleUploadedFile("proof.pdf", b"%PDF-1.4 test", content_type="application/pdf")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TicketCreatorTests(BaseWorkflowTests):
    def test_missing_required_attachment_raises(self):
        with self.assertRaises(TicketCreationError):
            create_student_ticket(
                student_profile=self.student,
                problem_type_id=self.problem.id,
                subject="Objet test",
                description="desc",
                uploaded_files_dict={},
                course_id=self.course.id,
            )
        self.assertEqual(Ticket.objects.count(), 0)

    def test_course_from_another_department_rejected(self):
        with self.assertRaises(TicketCreationError):
            create_student_ticket(
                student_profile=self.student,
                problem_type_id=self.problem.id,
                subject="Objet test",
                description="desc",
                uploaded_files_dict={str(self.config.id): self._file()},
                course_id=self.foreign_course.id,
            )

    def test_success_resolves_teacher_from_course_and_saves_attachment(self):
        ticket = create_student_ticket(
            student_profile=self.student,
            problem_type_id=self.problem.id,
            subject="Note manquante",
            description="Ma note manque.",
            uploaded_files_dict={str(self.config.id): self._file()},
            course_id=self.course.id,
        )
        self.assertEqual(ticket.status, Ticket.Status.SENT)
        self.assertEqual(ticket.teacher, self.teacher)
        self.assertEqual(ticket.attachments.count(), 1)

    def test_disallowed_extension_rejected(self):
        bad = SimpleUploadedFile("virus.exe", b"x", content_type="application/octet-stream")
        with self.assertRaises(TicketCreationError):
            create_student_ticket(
                student_profile=self.student,
                problem_type_id=self.problem.id,
                subject="Objet test",
                description="desc",
                uploaded_files_dict={str(self.config.id): bad},
                course_id=self.course.id,
            )


class StatusMachineTests(BaseWorkflowTests):
    def _ticket(self, status=Ticket.Status.SENT):
        return Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            subject="Objet test",
            description="desc",
            status=status,
        )

    def test_invalid_transition_rejected(self):
        ticket = self._ticket(Ticket.Status.SENT)
        with self.assertRaises(StatusTransitionError):
            apply_status(ticket, Ticket.Status.RESOLVED)

    def test_valid_transition_sets_received_at(self):
        ticket = self._ticket(Ticket.Status.SENT)
        apply_status(ticket, Ticket.Status.RECEIVED)
        self.assertIsNotNone(ticket.received_at)

    def test_rejection_requires_reason(self):
        ticket = self._ticket(Ticket.Status.PROCESSING)
        with self.assertRaises(StatusTransitionError):
            apply_status(ticket, Ticket.Status.REJECTED, reason="  ")

    def test_rejection_with_reason_sets_resolved_at(self):
        ticket = self._ticket(Ticket.Status.PROCESSING)
        apply_status(ticket, Ticket.Status.REJECTED, reason="Pièce illisible")
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.rejection_reason, "Pièce illisible")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StatusEndpointPermissionTests(BaseWorkflowTests):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            subject="Objet test",
            description="desc",
            status=Ticket.Status.PROCESSING,
        )

    def test_other_teacher_cannot_change_status(self):
        self.client.force_login(self.other_teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": str(self.ticket.id), "status": "RESOLVED"},
        )
        self.assertEqual(response.status_code, 403)

    def test_assigned_teacher_can_resolve(self):
        self.client.force_login(self.teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": str(self.ticket.id), "status": "RESOLVED"},
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.RESOLVED)

    def test_other_student_cannot_read_detail(self):
        self.client.force_login(self.other_student.user)
        response = self.client.get(f"/tickets/{self.ticket.id}/detail/")
        self.assertEqual(response.status_code, 403)

    def test_owner_student_can_read_detail(self):
        self.client.force_login(self.student.user)
        response = self.client.get(f"/tickets/{self.ticket.id}/detail/")
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_access_status_endpoint(self):
        self.client.force_login(self.student.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": str(self.ticket.id), "status": "RESOLVED"},
        )
        self.assertEqual(response.status_code, 403)


class ResolutionNoteTests(BaseWorkflowTests):
    """Réponse visible par l'étudiant sur une validation (RESOLVED)."""

    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create(
            student=self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            subject="Objet test",
            description="desc",
            status=Ticket.Status.PROCESSING,
        )

    def test_apply_status_stores_resolution_note(self):
        apply_status(
            self.ticket,
            Ticket.Status.RESOLVED,
            actor=self.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            resolution_note="Attestation générée, disponible à la scolarité.",
        )
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.resolution_note,
            "Attestation générée, disponible à la scolarité.",
        )
        entry = self.ticket.status_history.first()
        self.assertIn("Attestation générée", entry.note)

    def test_rejection_clears_resolution_note(self):
        self.ticket.resolution_note = "Réponse orpheline"
        self.ticket.save(update_fields=["resolution_note"])
        apply_status(
            self.ticket,
            Ticket.Status.REJECTED,
            reason="Pièce illisible",
            actor=self.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.resolution_note, "")

    def test_endpoint_stores_note_and_notifies_student(self):
        self.client.force_login(self.teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {
                "ticket_id": str(self.ticket.id),
                "status": "RESOLVED",
                "resolution_note": "Votre relevé est validé.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.resolution_note, "Votre relevé est validé.")

        # Le student lit la réponse dans son suivi.
        self.client.force_login(self.student.user)
        detail = self.client.get(f"/tickets/{self.ticket.id}/suivi/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Votre relevé est validé.")

    def test_student_notification_contains_resolution(self):
        from accounts.models import Notification

        self.client.force_login(self.teacher.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/tickets/ajax/status/",
                {
                    "ticket_id": str(self.ticket.id),
                    "status": "RESOLVED",
                    "resolution_note": "Dossier traité, réponse jointe.",
                },
            )
        notification = Notification.objects.filter(user=self.student.user).first()
        self.assertIsNotNone(notification)
        self.assertIn("Dossier traité, réponse jointe.", notification.body)
