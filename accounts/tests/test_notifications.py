"""Tests du centre de notifications : création, isolation, marquage « lu »."""

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Department, Faculty, Notification, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import Course, ProblemType
from tickets.models import Ticket
from tickets.services.status_machine import apply_status
from tickets.services.ticket_creator import create_student_ticket


class NotificationCreationTests(TestCase):
    def setUp(self):
        university = make_university()
        self.faculty = Faculty.objects.create(university=university, name="Sciences")
        self.dept = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.student = Student.objects.create(
            user=User.objects.create_user(username="ETU001", password="x"),
            registration_number="ETU001",
            faculty=self.faculty,
            department=self.dept,
        )
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
            name="Attestation", requires_course=False
        )

    def _create_ticket(self):
        return create_student_ticket(
            student_profile=self.student,
            problem_type_id=self.problem.id,
            subject="Attestation",
            description="attestation",
            uploaded_files_dict={},
            teacher_id=self.teacher.id,
            academic_year="2025-2026",
        )

    def test_ticket_creation_notifies_teacher_not_student(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._create_ticket()
        self.assertFalse(Notification.objects.filter(user=self.student.user).exists())
        self.assertTrue(Notification.objects.filter(user=self.teacher.user).exists())

    def test_teacher_status_change_notifies_student_not_teacher(self):
        with self.captureOnCommitCallbacks(execute=True):
            ticket = self._create_ticket()
        Notification.objects.all().delete()
        with self.captureOnCommitCallbacks(execute=True):
            apply_status(ticket, Ticket.Status.RECEIVED, actor=self.teacher.user)
        self.assertTrue(Notification.objects.filter(user=self.student.user).exists())
        self.assertFalse(Notification.objects.filter(user=self.teacher.user).exists())

    def test_notification_carries_ticket_reference(self):
        with self.captureOnCommitCallbacks(execute=True):
            ticket = self._create_ticket()
        notification = Notification.objects.get(user=self.teacher.user)
        self.assertEqual(notification.ticket_id, ticket.id)
        self.assertFalse(notification.is_read)


class NotificationViewTests(TestCase):
    def setUp(self):
        university = make_university()
        self.faculty = Faculty.objects.create(university=university, name="Sciences")
        self.dept = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.user = User.objects.create_user(username="ETU001", password="x")
        self.student = Student.objects.create(
            user=self.user, registration_number="ETU001",
            faculty=self.faculty, department=self.dept,
        )
        self.other_user = User.objects.create_user(username="ETU002", password="x")
        self.other_student = Student.objects.create(
            user=self.other_user, registration_number="ETU002",
            faculty=self.faculty, department=self.dept,
        )
        self.mine = Notification.objects.create(
            user=self.user, title="Ma notif", body="corps"
        )
        self.theirs = Notification.objects.create(
            user=self.other_user, title="Leur notif", body="corps"
        )

    def test_fragment_requires_authentication(self):
        response = self.client.get("/accounts/notifications/")
        self.assertEqual(response.status_code, 401)

    def test_fragment_shows_only_own_notifications(self):
        self.client.force_login(self.user)
        response = self.client.get("/accounts/notifications/")
        self.assertContains(response, "Ma notif")
        self.assertNotContains(response, "Leur notif")
        self.assertEqual(response.context["unread_count"], 1)

    def test_mark_read_without_ids_marks_all_own(self):
        Notification.objects.create(user=self.user, title="Encore", body="b")
        self.client.force_login(self.user)
        response = self.client.post("/accounts/ajax/notifications/read/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_notifications"], 0)
        self.assertFalse(
            Notification.objects.filter(user=self.user, is_read=False).exists()
        )
        # Celles des autres utilisateurs ne sont jamais touchées.
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)

    def test_mark_read_with_foreign_id_is_ignored(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/accounts/ajax/notifications/read/", {"ids": str(self.theirs.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 0)
        self.theirs.refresh_from_db()
        self.assertFalse(self.theirs.is_read)

    def test_mark_read_with_own_id(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/accounts/ajax/notifications/read/", {"ids": str(self.mine.id)}
        )
        self.assertEqual(response.json()["updated"], 1)
        self.mine.refresh_from_db()
        self.assertTrue(self.mine.is_read)

    def test_mark_read_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/accounts/ajax/notifications/read/").status_code, 405)

    def test_dashboard_shell_exposes_unread_badge(self):
        self.client.force_login(self.user)
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unread_notifications"], 1)
        labels = [item["label"] for item in response.context["nav_items"]]
        self.assertIn("Notifications", labels)
        badge_items = [item for item in response.context["nav_items"] if item.get("badge")]
        self.assertTrue(badge_items)
