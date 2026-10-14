"""
Routage de l'app tickets — namespace « tickets ».

  GET  /tickets/                       flux étudiant (mes requêtes)
  GET  /tickets/nouvelle/              fragment modale « Nouvelle requête »
  POST /tickets/ajax/create/           création d'un ticket (étudiant)
  POST /tickets/ajax/status/           changement de statut (enseignant)
  GET  /tickets/teacher/               boîte de réception (enseignant)
  GET  /tickets/<uuid:pk>/detail/      détail d'un ticket (propriétaire/enseignant)
  GET  /tickets/attachments/<uuid:pk>/ téléchargement protégé d'une pièce jointe
"""

from django.urls import path

from .views import ajax_actions, base, status_processor
from .views import student_dashboard, teacher_dashboard

app_name = "tickets"

urlpatterns = [
    path("", student_dashboard.student_feed, name="student_feed"),
    path("nouvelle/", base.student_request_modal, name="student_request_modal"),
    path("ajax/create/", ajax_actions.create_ticket, name="create_ticket"),
    path("ajax/status/", status_processor.update_status, name="update_status"),
    path("teacher/", teacher_dashboard.teacher_inbox, name="teacher_inbox"),
    path(
        "teacher/decision/",
        teacher_dashboard.teacher_decision_modal,
        name="teacher_decision_modal",
    ),
    path("<uuid:pk>/detail/", teacher_dashboard.ticket_detail, name="ticket_detail"),
    path(
        "attachments/<uuid:pk>/",
        teacher_dashboard.download_attachment,
        name="download_attachment",
    ),
]
