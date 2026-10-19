"""Tests de l'espace étudiant : suivi, réponse MORE_INFO, filtres, sécurité."""

import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Department, Faculty, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import Course, Enrollment, ProblemType
from tickets.models import Ticket, TicketComment, TicketStatusHistory
from tickets.services.status_machine import StatusTransitionError, apply_status


class StudentSpaceBase(TestCase):
    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.dept = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.teacher = Teacher.objects.create(
            user=User.objects.create_user(username="ENS001", password="x"),
            title="DR",
            faculty=self.faculty,
            department=self.dept,
        )
        self.course = Course.objects.create(
            code="INF101", name="Algo", department=self.dept,
            primary_instructor=self.teacher,
        )
        self.problem = ProblemType.objects.create(
            name="Note manquante", requires_course=True
        )
        self.simple_problem = ProblemType.objects.create(
            name="Attestation", requires_course=False
        )
        self.student = self._student("ETU001")
        self.other_student = self._student("ETU002")

    def _student(self, username):
        return Student.objects.create(
            user=User.objects.create_user(username=username, password="x"),
            registration_number=username,
            faculty=self.faculty,
            department=self.dept,
        )

    def _ticket(self, student=None, status=Ticket.Status.SENT, description="desc"):
        return Ticket.objects.create(
            student=student or self.student,
            teacher=self.teacher,
            course=self.course,
            problem_type=self.problem,
            description=description,
            status=status,
            rejection_reason="motif" if status == Ticket.Status.REJECTED else "",
        )


class StudentHomeTests(StudentSpaceBase):
    def test_home_requires_authentication(self):
        response = self.client.get("/tickets/accueil/")
        self.assertEqual(response.status_code, 401)

    def test_home_forbidden_for_teacher(self):
        self.client.force_login(self.teacher.user)
        response = self.client.get("/tickets/accueil/")
        self.assertEqual(response.status_code, 403)

    def test_home_shows_own_stats_only(self):
        self._ticket()
        self._ticket(student=self.other_student, status=Ticket.Status.RESOLVED)
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/accueil/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["total"], 1)


class StudentFeedTests(StudentSpaceBase):
    def test_feed_search_filters_by_description(self):
        self._ticket(description="note manquante session unique")
        self._ticket(description="autre sujet")
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/", {"q": "unique"})
        self.assertEqual(len(response.context["tickets"]), 1)

    def test_feed_status_filter(self):
        self._ticket(status=Ticket.Status.PROCESSING)
        self._ticket(status=Ticket.Status.REJECTED)
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/", {"status": "PROCESSING"})
        self.assertEqual(len(response.context["tickets"]), 1)
        self.assertEqual(response.context["tickets"][0].status, "PROCESSING")

    def test_feed_pagination(self):
        for index in range(12):
            self._ticket(description=f"sujet {index}")
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/")
        self.assertEqual(len(response.context["tickets"]), 10)
        self.assertEqual(response.context["page_obj"].paginator.count, 12)
        response = self.client.get("/tickets/", {"page": 2})
        self.assertEqual(len(response.context["tickets"]), 2)

    def test_feed_never_shows_foreign_tickets(self):
        self._ticket(student=self.other_student)
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/")
        self.assertEqual(len(response.context["tickets"]), 0)


class StudentDetailTests(StudentSpaceBase):
    def test_owner_can_open_suivi(self):
        ticket = self._ticket()
        self.client.force_login(self.student.user)
        response = self.client.get(f"/tickets/{ticket.id}/suivi/")
        self.assertEqual(response.status_code, 200)

    def test_foreign_ticket_returns_404(self):
        ticket = self._ticket(student=self.other_student)
        self.client.force_login(self.student.user)
        response = self.client.get(f"/tickets/{ticket.id}/suivi/")
        self.assertEqual(response.status_code, 404)

    def test_anonymous_gets_401(self):
        ticket = self._ticket()
        response = self.client.get(f"/tickets/{ticket.id}/suivi/")
        self.assertEqual(response.status_code, 401)

    def test_detail_renders_history_and_question(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        ticket.complementary_info_request = "Envoyez le relevé."
        ticket.save(update_fields=["complementary_info_request"])
        self.client.force_login(self.student.user)
        response = self.client.get(
            f"/tickets/{ticket.id}/suivi/", HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertContains(response, "Envoyez le relevé.")


class StudentReplyTests(StudentSpaceBase):
    def _reply(self, ticket, body="Voici le relevé.", extra=None):
        self.client.force_login(self.student.user)
        data = {"ticket_id": ticket.id, "body": body}
        if extra:
            data.update(extra)
        return self.client.post("/tickets/ajax/reply/", data)

    def test_reply_moves_more_info_to_processing(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        response = self._reply(ticket)
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)
        self.assertEqual(TicketComment.objects.filter(ticket=ticket).count(), 1)

    def test_reply_rejected_without_body(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        response = self._reply(ticket, body="  ")
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.MORE_INFO)

    def test_reply_rejected_when_not_more_info(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self._reply(ticket)
        self.assertEqual(response.status_code, 400)

    def test_reply_foreign_ticket_404(self):
        ticket = self._ticket(student=self.other_student, status=Ticket.Status.MORE_INFO)
        response = self._reply(ticket)
        self.assertEqual(response.status_code, 404)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_reply_with_file_stores_attachment(self):
        """L'étudiant joint le document demandé à sa réponse MORE_INFO."""
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        response = self._reply(
            ticket,
            extra={
                "file": SimpleUploadedFile(
                    "releve.pdf", b"%PDF-1.4 test", content_type="application/pdf"
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        comment = TicketComment.objects.get(ticket=ticket)
        self.assertTrue(comment.file)
        self.assertEqual(comment.file_extension, "pdf")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_reply_rejects_forbidden_file_extension(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        response = self._reply(
            ticket,
            extra={
                "file": SimpleUploadedFile(
                    "evil.html", b"<b>hi</b>", content_type="text/html"
                )
            },
        )
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.MORE_INFO)
        self.assertEqual(TicketComment.objects.filter(ticket=ticket).count(), 0)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_reply_oversized_file_rejected(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        big = SimpleUploadedFile("big.pdf", b"x" * 1024, content_type="application/pdf")
        with override_settings(MAX_UPLOAD_SIZE=512):
            response = self._reply(ticket, extra={"file": big})
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.MORE_INFO)


class MoreInfoTransitionTests(StudentSpaceBase):
    def test_more_info_requires_question(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        with self.assertRaises(StatusTransitionError):
            apply_status(ticket, Ticket.Status.MORE_INFO, actor=self.teacher.user)

    def test_more_info_stores_question_and_history_note(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        apply_status(
            ticket,
            Ticket.Status.MORE_INFO,
            actor=self.teacher.user,
            more_info_request="Justificatif ?",
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.complementary_info_request, "Justificatif ?")
        entry = TicketStatusHistory.objects.filter(
            ticket=ticket, to_status=Ticket.Status.MORE_INFO
        ).first()
        self.assertEqual(entry.note, "Justificatif ?")

    def test_resuming_processing_archives_question(self):
        ticket = self._ticket(status=Ticket.Status.MORE_INFO)
        ticket.complementary_info_request = "Justificatif ?"
        ticket.save(update_fields=["complementary_info_request"])
        apply_status(ticket, Ticket.Status.PROCESSING, actor=self.teacher.user)
        ticket.refresh_from_db()
        self.assertEqual(ticket.complementary_info_request, "")

    def test_teacher_status_endpoint_requires_question(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": ticket.id, "status": "MORE_INFO"},
        )
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)

    def test_teacher_status_endpoint_accepts_question(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": ticket.id, "status": "MORE_INFO",
             "more_info_request": "Relevé signé ?"},
        )
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.MORE_INFO)


class EnrollmentFilterTests(StudentSpaceBase):
    def setUp(self):
        super().setUp()
        self.other_course = Course.objects.create(
            code="INF202", name="Bases de données", department=self.dept,
            primary_instructor=self.teacher,
        )
        Enrollment.objects.create(student=self.student, course=self.course)

    def _config(self):
        self.client.force_login(self.student.user)
        return self.client.get(
            "/scolarite/ajax/form-config/", {"problem_type_id": self.problem.id}
        )

    def test_config_only_lists_enrolled_courses(self):
        response = self._config()
        codes = [course["code"] for course in response.json()["courses"]]
        self.assertEqual(codes, ["INF101"])
        self.assertTrue(response.json()["enrollment_filtered"])

    def test_config_falls_back_to_department_without_enrollment(self):
        Enrollment.objects.filter(student=self.student).delete()
        response = self._config()
        codes = [course["code"] for course in response.json()["courses"]]
        self.assertGreaterEqual(len(codes), 2)
        self.assertFalse(response.json()["enrollment_filtered"])

    def test_create_rejects_unenrolled_course(self):
        self.client.force_login(self.student.user)
        response = self.client.post(
            "/tickets/ajax/create/",
            {
                "problem_type_id": self.problem.id,
                "course_id": self.other_course.id,
                "subject": "Demande",
                "description": "demande",
            },
        )
        self.assertEqual(response.status_code, 400)


class AcademicYearTests(StudentSpaceBase):
    def test_create_ticket_stores_academic_year(self):
        self.client.force_login(self.student.user)
        response = self.client.post(
            "/tickets/ajax/create/",
            {
                "problem_type_id": self.simple_problem.id,
                "teacher_id": self.teacher.id,
                "subject": "Attestation stage",
                "description": "attestation pour stage",
                "academic_year": "2025-2026",
            },
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.json()["ticket_id"])
        self.assertEqual(ticket.academic_year, "2025-2026")

    def test_academic_year_truncated_to_nine_chars(self):
        self.client.force_login(self.student.user)
        response = self.client.post(
            "/tickets/ajax/create/",
            {
                "problem_type_id": self.simple_problem.id,
                "teacher_id": self.teacher.id,
                "subject": "Attestation",
                "description": "attestation",
                "academic_year": "2025-2026-surcharge",
            },
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.json()["ticket_id"])
        self.assertEqual(ticket.academic_year, "2025-2026")

    def test_modal_exposes_current_academic_year(self):
        self.client.force_login(self.student.user)
        response = self.client.get("/tickets/nouvelle/")
        self.assertEqual(response.status_code, 200)
        years = response.context["academic_years"]
        self.assertIn(response.context["current_academic_year"], years)
        self.assertEqual(len(years[0]), 9)
