"""
Tests de l'espace enseignant (ARCHITECTURE §7.3, §9, §10).

Couvre : permissions/périmètre (IDOR), auto-acquittement à l'ouverture de la
boîte, filtres, transitions et notifications, feature flag MORE_INFO, accès
protégé aux pièces jointes, et consumer WebSocket (authentification, isolation
des groupes, canal lecture seule).
"""

import json
import tempfile

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import Department, Faculty, Notification, Student, Teacher
from accounts.tests.factories import make_university
from core_scolarite.models import AttachmentConfig, Course, ProblemType
from tickets.consumers import TicketConsumer
from tickets.models import Ticket, TicketAttachment, TicketStatusHistory


class TeacherSpaceSetupMixin:
    """Socle partagé : université, deux enseignants, étudiant, ticket de base.

    Mixin (sans TestCase) pour permettre aux consumers WS d'hériter de
    `TransactionTestCase` — requis quand le consumer touche à la base depuis
    un autre thread (SQLite in-memory partagé).
    """

    def setUp(self):
        self.university = make_university()
        self.faculty = Faculty.objects.create(university=self.university, name="Sciences")
        self.info = Department.objects.create(faculty=self.faculty, name="Informatique")
        self.math = Department.objects.create(faculty=self.faculty, name="Mathématiques")

        self.student = self._student("ETU001", self.info)
        self.other_student = self._student("ETU002", self.info)
        self.teacher = self._teacher("ENS001", self.info)
        self.other_teacher = self._teacher("ENS002", self.math)

        self.course = Course.objects.create(
            code="INF101",
            name="Algo",
            department=self.info,
            primary_instructor=self.teacher,
        )
        self.problem = ProblemType.objects.create(
            name="Note manquante", requires_course=True
        )
        self.config = AttachmentConfig.objects.create(
            problem_type=self.problem, label="Résultat du portail", is_required=True
        )

    def _student(self, username, department, faculty=None):
        return Student.objects.create(
            user=User.objects.create_user(username=username, password="x"),
            registration_number=username,
            faculty=faculty or department.faculty,
            department=department,
        )

    def _teacher(self, username, department):
        return Teacher.objects.create(
            user=User.objects.create_user(username=username, password="x"),
            title="DR",
            faculty=department.faculty,
            department=department,
        )

    def _ticket(self, teacher=None, status=Ticket.Status.RECEIVED, **kwargs):
        defaults = {
            "student": self.student,
            "teacher": teacher or self.teacher,
            "course": self.course,
            "problem_type": self.problem,
            "description": "Ma note manque sur le portail.",
            "status": status,
        }
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)


class TeacherSpaceBase(TeacherSpaceSetupMixin, TestCase):
    """Socle des tests HTTP (transactions encapsulées par TestCase)."""

    pass


class TeacherPermissionsTests(TeacherSpaceBase):
    """Périmètre strict : chaque endpoint n'expose que les tickets assignés."""

    def test_anonymous_gets_401_on_all_teacher_endpoints(self):
        for url in (
            "/tickets/teacher/accueil/",
            "/tickets/teacher/",
            "/tickets/teacher/list/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

    def test_student_gets_403_on_teacher_endpoints(self):
        self.client.force_login(self.student.user)
        for url in ("/tickets/teacher/", "/tickets/teacher/list/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_inbox_shows_only_own_tickets(self):
        mine = self._ticket(status=Ticket.Status.RECEIVED)
        foreign = self._ticket(teacher=self.other_teacher, status=Ticket.Status.RECEIVED)
        self.client.force_login(self.teacher.user)
        response = self.client.get("/tickets/teacher/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, mine.id)
        self.assertNotContains(response, foreign.id)

    def test_other_teacher_cannot_open_detail_by_uuid(self):
        ticket = self._ticket()
        self.client.force_login(self.other_teacher.user)
        response = self.client.get(f"/tickets/{ticket.id}/detail/")
        self.assertEqual(response.status_code, 403)

    def test_assigned_teacher_opens_detail_with_decision_rights(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.teacher.user)
        response = self.client.get(f"/tickets/{ticket.id}/detail/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["can_decide"], True)
        # Boutons de décision réservés à l'enseignant assigné.
        self.assertContains(response, "Valider")

    def test_owner_student_sees_detail_without_decision_actions(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.student.user)
        response = self.client.get(f"/tickets/{ticket.id}/detail/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["can_decide"], False)
        self.assertNotContains(response, "data-status-action")

    def test_decision_modal_refuses_foreign_ticket(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.other_teacher.user)
        response = self.client.get(
            f"/tickets/teacher/decision/?ticket_id={ticket.id}&target=RESOLVED"
        )
        self.assertEqual(response.status_code, 404)

    def test_status_endpoint_requires_teacher_role(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.student.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": str(ticket.id), "status": "RESOLVED"},
        )
        self.assertEqual(response.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)

    def test_status_endpoint_rejects_foreign_ticket(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.client.force_login(self.other_teacher.user)
        response = self.client.post(
            "/tickets/ajax/status/",
            {"ticket_id": str(ticket.id), "status": "RESOLVED"},
        )
        self.assertEqual(response.status_code, 403)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)


class TeacherInboxFlowTests(TeacherSpaceBase):
    """Ouverture de la boîte : acquittement automatique SENT → RECEIVED."""

    def test_opening_inbox_acknowledges_sent_tickets(self):
        ticket = self._ticket(status=Ticket.Status.SENT)
        self.client.force_login(self.teacher.user)
        self.client.get("/tickets/teacher/")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RECEIVED)
        self.assertIsNotNone(ticket.received_at)
        entry = ticket.status_history.latest("created_at")
        self.assertEqual(entry.from_status, Ticket.Status.SENT)
        self.assertEqual(entry.to_status, Ticket.Status.RECEIVED)
        self.assertEqual(entry.actor, self.teacher.user)

    def test_inbox_list_endpoint_does_not_acknowledge(self):
        """La liste seule (refresh temps réel) ne déclenche aucune mutation."""
        ticket = self._ticket(status=Ticket.Status.SENT)
        self.client.force_login(self.teacher.user)
        self.client.get("/tickets/teacher/list/")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.SENT)

    def test_acknowledge_notifies_student(self):
        ticket = self._ticket(status=Ticket.Status.SENT)
        self.client.force_login(self.teacher.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get("/tickets/teacher/")
        self.assertTrue(
            Notification.objects.filter(
                user=self.student.user, ticket=ticket, is_read=False
            ).exists()
        )
        # L'acteur ne reçoit jamais sa propre notification.
        self.assertFalse(
            Notification.objects.filter(user=self.teacher.user, ticket=ticket).exists()
        )

    def test_dashboard_overview_counts_by_group(self):
        self._ticket(status=Ticket.Status.SENT)
        self._ticket(status=Ticket.Status.RECEIVED)
        self._ticket(status=Ticket.Status.PROCESSING)
        self._ticket(status=Ticket.Status.RESOLVED)
        self.client.force_login(self.teacher.user)
        response = self.client.get("/tickets/teacher/accueil/")
        self.assertEqual(response.status_code, 200)
        stats = response.context["stats"]
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["awaiting"], 1)
        self.assertEqual(stats["in_progress"], 1)
        self.assertEqual(stats["done"], 1)


class TeacherInboxFilterTests(TeacherSpaceBase):
    """Recherche et filtres : statut, motif, faculté, département, cours, dates."""

    def setUp(self):
        super().setUp()
        self.received = self._ticket(status=Ticket.Status.RECEIVED)
        self.processing = self._ticket(status=Ticket.Status.PROCESSING)
        self.foreign = self._ticket(
            teacher=self.other_teacher, status=Ticket.Status.RECEIVED
        )
        self.client.force_login(self.teacher.user)

    def _ids(self, response):
        return {t.id for t in response.context["tickets"]}

    def test_status_filter(self):
        response = self.client.get("/tickets/teacher/", {"status": "PROCESSING"})
        self.assertEqual(self._ids(response), {self.processing.id})

    def test_search_matches_student_and_description(self):
        response = self.client.get("/tickets/teacher/", {"q": "ETU001"})
        self.assertEqual(self._ids(response), {self.received.id, self.processing.id})
        response = self.client.get("/tickets/teacher/", {"q": "portail"})
        self.assertEqual(self._ids(response), {self.received.id, self.processing.id})

    def test_course_filter(self):
        other_course = Course.objects.create(
            code="INF202", name="BDD", department=self.info
        )
        self._ticket(status=Ticket.Status.RECEIVED, course=other_course)
        response = self.client.get(
            "/tickets/teacher/", {"course": str(other_course.id)}
        )
        self.assertEqual(len(self._ids(response)), 1)

    def test_faculty_and_department_filters(self):
        response = self.client.get(
            "/tickets/teacher/", {"faculty": str(self.faculty.id)}
        )
        # Tous les tickets visibles appartiennent à la faculté de test.
        self.assertEqual(len(self._ids(response)), 2)
        response = self.client.get(
            "/tickets/teacher/", {"department": str(self.info.id)}
        )
        self.assertEqual(len(self._ids(response)), 2)

    def test_invalid_filter_values_never_crash(self):
        response = self.client.get(
            "/tickets/teacher/",
            {
                "status": "HACKED",
                "problem_type": "not-a-uuid",
                "date_from": "2026-99-99",
                "date_to": "???",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self._ids(response)), 2)

    def test_pagination_is_scoped_and_ordered(self):
        for _ in range(12):
            self._ticket(status=Ticket.Status.RECEIVED)
        response = self.client.get("/tickets/teacher/", {"page": "2"})
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        # 13 RECEIVED + 1 PROCESSING, tous assignés à self.teacher.
        self.assertEqual(page.paginator.count, 14)
        # Priorité : RECEIVED (1) avant PROCESSING (3) ; anti-chronologique ensuite.
        page_one = list(self.client.get("/tickets/teacher/").context["tickets"])
        self.assertEqual(page_one[0].status, Ticket.Status.RECEIVED)
        self.assertEqual(list(page.object_list)[-1].id, self.processing.id)


class TeacherDecisionTests(TeacherSpaceBase):
    """Décisions enseignant : transitions, motif obligatoire, flag MORE_INFO."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.teacher.user)

    def _post_status(self, ticket, status, **extra):
        data = {"ticket_id": str(ticket.id), "status": status}
        data.update(extra)
        return self.client.post("/tickets/ajax/status/", data)

    def test_start_processing_moves_to_processing(self):
        ticket = self._ticket(status=Ticket.Status.RECEIVED)
        response = self._post_status(ticket, Ticket.Status.PROCESSING)
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)

    def test_resolve_journals_history_and_notifies_student(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
        entry = ticket.status_history.latest("created_at")
        self.assertEqual(entry.to_status, Ticket.Status.RESOLVED)
        self.assertEqual(entry.actor_role, TicketStatusHistory.ActorRole.TEACHER)
        self.assertTrue(
            Notification.objects.filter(
                user=self.student.user, ticket=ticket, title="Requête résolue"
            ).exists()
        )

    def test_reject_without_reason_is_refused(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self._post_status(ticket, Ticket.Status.REJECTED, rejection_reason="  ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("rejection_reason", response.json()["errors"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)
        self.assertIsNone(ticket.rejection_reason)

    def test_reject_with_reason_is_journalized(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self._post_status(
            ticket, Ticket.Status.REJECTED, rejection_reason="Pièce illisible."
        )
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.REJECTED)
        self.assertEqual(ticket.rejection_reason, "Pièce illisible.")
        entry = ticket.status_history.latest("created_at")
        self.assertIn("Pièce illisible.", entry.note)

    def test_invalid_transition_is_refused(self):
        ticket = self._ticket(status=Ticket.Status.RECEIVED)
        # RECEIVED → RESOLVED saute PROCESSING : refusé.
        response = self._post_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RECEIVED)

    def test_terminal_state_is_immutable(self):
        ticket = self._ticket(status=Ticket.Status.RESOLVED)
        response = self._post_status(ticket, Ticket.Status.PROCESSING)
        self.assertEqual(response.status_code, 400)

    def test_stale_instance_yields_conflict(self):
        """Décision concurrente : le ticket a muté entre lecture et écriture."""
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        stale = Ticket.objects.get(pk=ticket.pk)
        self._post_status(ticket, Ticket.Status.RESOLVED)
        from tickets.services.status_machine import (
            StatusTransitionError,
            apply_status,
        )

        with self.assertRaises(StatusTransitionError):
            apply_status(stale, Ticket.Status.REJECTED, reason="Trop tard.")

    def test_more_info_requires_question(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self._post_status(ticket, Ticket.Status.MORE_INFO)
        self.assertEqual(response.status_code, 400)
        self.assertIn("complementary_info_request", response.json()["errors"])

    def test_more_info_with_question_notifies_student(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_status(
                ticket,
                Ticket.Status.MORE_INFO,
                more_info_request="Envoyez le relevé signé.",
            )
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.MORE_INFO)
        self.assertEqual(ticket.complementary_info_request, "Envoyez le relevé signé.")
        self.assertTrue(
            Notification.objects.filter(user=self.student.user, ticket=ticket).exists()
        )

    @override_settings(ENABLE_TEACHER_MORE_INFO=False)
    def test_more_info_disabled_returns_400_without_side_effect(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self._post_status(
            ticket, Ticket.Status.MORE_INFO, more_info_request="Hello?"
        )
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.PROCESSING)
        self.assertEqual(ticket.complementary_info_request, "")

    @override_settings(ENABLE_TEACHER_MORE_INFO=False)
    def test_more_info_button_hidden_when_flag_disabled(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self.client.get(f"/tickets/{ticket.id}/detail/")
        self.assertNotContains(response, "target=MORE_INFO")

    @override_settings(ENABLE_TEACHER_MORE_INFO=True)
    def test_more_info_button_visible_when_flag_enabled(self):
        ticket = self._ticket(status=Ticket.Status.PROCESSING)
        response = self.client.get(f"/tickets/{ticket.id}/detail/")
        self.assertContains(response, "target=MORE_INFO")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TeacherAttachmentAccessTests(TeacherSpaceBase):
    """Service de fichier protégé : appartenance vérifiée, inline borné."""

    def setUp(self):
        super().setUp()
        self.ticket = self._ticket(status=Ticket.Status.PROCESSING)
        self.attachment = TicketAttachment.objects.create(
            ticket=self.ticket,
            config=self.config,
            file=SimpleUploadedFile(
                "proof.pdf", b"%PDF-1.4 test", content_type="application/pdf"
            ),
        )
        self.url = f"/tickets/attachments/{self.attachment.id}/"

    def test_assigned_teacher_downloads(self):
        self.client.force_login(self.teacher.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"].split(";")[0], "attachment"
        )
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_owner_student_downloads(self):
        self.client.force_login(self.student.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_other_teacher_gets_403(self):
        self.client.force_login(self.other_teacher.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_other_student_gets_403(self):
        self.client.force_login(self.other_student.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_inline_consultation_for_pdf(self):
        self.client.force_login(self.teacher.user)
        response = self.client.get(self.url, {"inline": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("inline;"))

    def test_inline_forbidden_extension_falls_back_to_attachment(self):
        """Une extension hors whitelist ne sera jamais servie en inline."""
        evil = TicketAttachment.objects.create(
            ticket=self.ticket,
            config=self.config,
            file=SimpleUploadedFile(
                "evil.html", b"<b>hi</b>", content_type="text/html"
            ),
        )
        self.client.force_login(self.teacher.user)
        response = self.client.get(f"/tickets/attachments/{evil.id}/", {"inline": "1"})
        self.assertEqual(
            response["Content-Disposition"].split(";")[0], "attachment"
        )
        self.assertEqual(response["Content-Type"], "application/octet-stream")


class TeacherConsumerTests(TeacherSpaceSetupMixin, TransactionTestCase):
    """Consumer WebSocket : auth à la connexion, isolation, lecture seule.

    `TransactionTestCase` est requis : le consumer accède à la base depuis le
    thread ASGI (SQLite in-memory partagé), ce que `TestCase` interdit.
    """

    def _communicator(self, user):
        """Communicateur avec l'utilisateur injecté dans le scope (sans middleware)."""
        communicator = WebsocketCommunicator(TicketConsumer.as_asgi(), "/ws/tickets/")
        communicator.scope["user"] = user
        return communicator

    def test_anonymous_connection_rejected_4401(self):
        async def scenario():
            communicator = self._communicator(AnonymousUser())
            # Accept puis fermeture 4401 : le navigateur reçoit un vrai code
            # de fermeture (un refus avant accept serait une « failed » brute).
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            reply = await communicator.receive_output(timeout=2)
            self.assertEqual(reply["type"], "websocket.close")
            self.assertEqual(reply["code"], 4401)
            await communicator.disconnect()

        async_to_sync(scenario)()

    def test_user_without_profile_rejected_4403(self):
        bare_user = User.objects.create_user(username="ghost", password="x")

        async def scenario():
            communicator = self._communicator(bare_user)
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            reply = await communicator.receive_output(timeout=2)
            self.assertEqual(reply["type"], "websocket.close")
            self.assertEqual(reply["code"], 4403)
            await communicator.disconnect()

        async_to_sync(scenario)()

    def test_teacher_receives_events_for_own_group_only(self):
        """Chaque enseignant ne reçoit que les événements de ses requêtes."""

        async def scenario():
            mine = self._communicator(self.teacher.user)
            foreign = self._communicator(self.other_teacher.user)
            self.assertTrue((await mine.connect())[0])
            self.assertTrue((await foreign.connect())[0])

            channel_layer = get_channel_layer()
            await channel_layer.group_send(
                f"user_{self.teacher.user.id}",
                {
                    "type": "ticket.status.changed",
                    "message": {"ticket_id": "abc", "status": "RESOLVED"},
                },
            )
            received = json.loads(await mine.receive_from(timeout=2))
            self.assertEqual(received["status"], "RESOLVED")

            # L'autre enseignant ne reçoit rien (son groupe n'est pas sollicité).
            self.assertTrue(await foreign.receive_nothing(timeout=0.3))

            await mine.disconnect()
            await foreign.disconnect()

        async_to_sync(scenario)()

    def test_websocket_rejects_mutation_attempts(self):
        """Canal lecture seule : toute mutation WS est refusée sans effet."""
        ticket = self._ticket(status=Ticket.Status.RECEIVED)

        async def scenario():
            communicator = self._communicator(self.teacher.user)
            self.assertTrue((await communicator.connect())[0])
            await communicator.send_to(
                text_data=json.dumps(
                    {
                        "action": "update_status",
                        "ticket_id": str(ticket.id),
                        "status": "RESOLVED",
                    }
                )
            )
            reply = json.loads(await communicator.receive_from(timeout=2))
            self.assertEqual(reply["type"], "error")
            self.assertEqual(reply["code"], "mutation_forbidden")
            await communicator.disconnect()

        async_to_sync(scenario)()
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RECEIVED)

