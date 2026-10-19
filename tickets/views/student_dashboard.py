"""
Espace étudiant — tickets (ARCHITECTURE §7.3).

  * `student_home`      : tableau de bord (statistiques, activités récentes,
    compteur de notifications non lues).
  * `student_feed`      : « Mes requêtes » — recherche, filtre de statut,
    pagination (binding session uniquement).
  * `student_ticket_detail` : suivi d'une requête — chronologie horodatée,
    commentaires, formulaire de réponse si demande d'informations.
  * `student_reply`     : dépôt d'une réponse à une demande d'informations
    complémentaires (→ transition MORE_INFO → PROCESSING).

Règle anti-falsification (IDOR) : le queryset est toujours filtré par
`request.student` — un identifiant de profil n'est jamais lu côté client, et
une requête appartenant à un autre étudiant renvoie 404 (existence masquée).
"""

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import student_required
from accounts.spa import spa_page
from accounts.models import Notification
from tickets.models import Ticket, TicketComment, TicketStatusHistory
from tickets.services.status_machine import StatusTransitionError, apply_status

FEED_PAGE_SIZE = 10
OPEN_STATUSES = (
    Ticket.Status.SENT,
    Ticket.Status.RECEIVED,
    Ticket.Status.MORE_INFO,
    Ticket.Status.PROCESSING,
)


@spa_page
@student_required
def student_home(request):
    """Tableau de bord étudiant : stats, dernières activités, notifications."""
    tickets = Ticket.objects.filter(student=request.student)
    stats = tickets.aggregate(
        total=Count("id"),
        open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        more_info=Count("id", filter=Q(status=Ticket.Status.MORE_INFO)),
        resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
        rejected=Count("id", filter=Q(status=Ticket.Status.REJECTED)),
    )
    recent = (
        tickets.select_related("course", "problem_type", "teacher__user")
        .order_by("-created_at")[:5]
    )
    unread = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()
    return render(
        request,
        "partials/student_home.html",
        {"stats": stats, "recent": recent, "unread_notifications": unread},
    )


@spa_page
@student_required
def student_feed(request):
    """Fragment « Mes requêtes » : recherche `q`, filtre `status`, `page`."""
    tickets = Ticket.objects.filter(student=request.student).select_related(
        "course", "problem_type", "teacher__user"
    )

    query = (request.GET.get("q") or "").strip()
    if query:
        tickets = tickets.filter(
            Q(description__icontains=query)
            | Q(problem_type__name__icontains=query)
            | Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
        )

    status = (request.GET.get("status") or "").strip()
    if status in Ticket.Status.values:
        tickets = tickets.filter(status=status)

    tickets = tickets.order_by("-created_at")
    paginator = Paginator(tickets, FEED_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "partials/student_feed.html",
        {
            "page_obj": page,
            "tickets": page.object_list,
            "query": query,
            "active_status": status,
            "status_choices": Ticket.Status.choices,
            "total_count": paginator.count,
        },
    )


@spa_page
@student_required
def student_ticket_detail(request, pk):
    """Suivi d'une requête appartenant à l'étudiant connecté (sinon 404)."""
    ticket = (
        Ticket.objects.filter(pk=pk, student=request.student)
        .select_related("course", "problem_type", "teacher__user", "student__user")
        .prefetch_related("status_history__actor", "comments__author", "attachments__config")
        .first()
    )
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )
    return render(
        request, "partials/student_ticket_detail.html", {"ticket": ticket}
    )


@require_POST
@student_required
def student_reply(request):
    """
    Réponse de l'étudiant à une demande d'informations complémentaires.

    Crée un `TicketComment` puis fait muter MORE_INFO → PROCESSING (l'enseignant
    retrouve la requête en cours d'analyse dans sa boîte).
    """
    ticket_id = request.POST.get("ticket_id")
    body = (request.POST.get("body") or "").strip()

    ticket = Ticket.objects.filter(pk=ticket_id, student=request.student).first()
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )
    if not body:
        return JsonResponse(
            {
                "status": "error",
                "message": str(_("Votre réponse est obligatoire.")),
                "errors": {"body": str(_("Champ obligatoire."))},
            },
            status=400,
        )
    if ticket.status != Ticket.Status.MORE_INFO:
        return JsonResponse(
            {
                "status": "error",
                "message": str(
                    _("Aucune demande d'informations en attente sur cette requête.")
                ),
            },
            status=400,
        )

    TicketComment.objects.create(ticket=ticket, author=request.user, body=body)
    try:
        apply_status(
            ticket,
            Ticket.Status.PROCESSING,
            actor=request.user,
            actor_role=TicketStatusHistory.ActorRole.STUDENT,
            note=str(_("Réponse fournie par l'étudiant.")),
        )
    except StatusTransitionError as exc:
        return JsonResponse(
            {"status": "error", "message": exc.message, "errors": exc.field_errors},
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Réponse transmise à l'enseignant.")),
            "ticket_status": ticket.status,
            "status_label": ticket.status_label,
        },
        status=200,
    )
