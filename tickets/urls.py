"""
Routage de l'app tickets — namespace « tickets ».

  GET  /tickets/                       flux étudiant (mes requêtes, filtres)
  GET  /tickets/accueil/               tableau de bord étudiant (stats)
  GET  /tickets/nouvelle/              fragment modale « Nouvelle requête »
  POST /tickets/ajax/create/           création d'un ticket (étudiant)
  POST /tickets/ajax/reply/            réponse à une demande d'informations
  POST /tickets/ajax/status/           changement de statut (enseignant)
  GET  /tickets/teacher/               boîte de réception (enseignant)
  GET  /tickets/<uuid:pk>/detail/      détail d'un ticket (propriétaire/enseignant)
  GET  /tickets/<uuid:pk>/suivi/       suivi d'un ticket (étudiant propriétaire)
  GET  /tickets/attachments/<uuid:pk>/ téléchargement protégé d'une pièce jointe
"""

from django.urls import path

from .views import ajax_actions, base, status_processor
from .views import student_dashboard, teacher_dashboard

app_name = "tickets"

urlpatterns = [
    path("", student_dashboard.student_feed, name="student_feed"),
    path("accueil/", student_dashboard.student_home, name="student_home"),
    path("nouvelle/", base.student_request_modal, name="student_request_modal"),
    path("ajax/create/", ajax_actions.create_ticket, name="create_ticket"),
    path("ajax/reply/", student_dashboard.student_reply, name="student_reply"),
    path("ajax/status/", status_processor.update_status, name="update_status"),
    path("teacher/", teacher_dashboard.teacher_inbox, name="teacher_inbox"),
    path(
        "teacher/decision/",
        teacher_dashboard.teacher_decision_modal,
        name="teacher_decision_modal",
    ),
    path("<uuid:pk>/detail/", teacher_dashboard.ticket_detail, name="ticket_detail"),
    path(
        "<uuid:pk>/suivi/",
        student_dashboard.student_ticket_detail,
        name="student_ticket_detail",
    ),
    path(
        "attachments/<uuid:pk>/",
        teacher_dashboard.download_attachment,
        name="download_attachment",
    ),
]
