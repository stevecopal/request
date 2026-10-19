"""
Espace étudiant — tickets (ARCHITECTURE §7.3).

  * `student_home`      : tableau de bord (statistiques granulaires, activités
    récentes, dernières notifications).
  * `student_feed`      : « Mes requêtes » — recherche (n°, objet, catégorie),
    filtres statut/date, tri, pagination (binding session uniquement).
  * `student_ticket_detail` : suivi d'une requête — étape actuelle, service
    responsable, réponses au formulaire, chronologie, commentaires, formulaire
    de réponse si demande d'informations.
  * `student_reply`     : dépôt d'une réponse à une demande d'informations
    complémentaires (→ transition MORE_INFO → PROCESSING).

Règle anti-falsification (IDOR) : le queryset est toujours filtré par
`request.student` — un identifiant de profil n'est jamais lu côté client, et
une requête appartenant à un autre étudiant renvoie 404 (existence masquée).
"""

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from urllib.parse import urlencode

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
PENDING_STATUSES = (Ticket.Status.SENT, Ticket.Status.RECEIVED)
DONE_STATUSES = (Ticket.Status.RESOLVED, Ticket.Status.REJECTED)
# Tri blanc-liste côté serveur (aucun champ dynamique depuis le client).
FEED_SORTS = {
    "created_desc": "-created_at",
    "created_asc": "created_at",
    "updated_desc": "-updated_at",
    "updated_asc": "updated_at",
}
FEED_DEFAULT_SORT = "created_desc"


@spa_page
@student_required
def student_home(request):
    """Tableau de bord étudiant : stats granulaires, activités, notifications."""
    tickets = Ticket.objects.filter(student=request.student)
    stats = tickets.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status__in=PENDING_STATUSES)),
        processing=Count("id", filter=Q(status=Ticket.Status.PROCESSING)),
        more_info=Count("id", filter=Q(status=Ticket.Status.MORE_INFO)),
        resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
        rejected=Count("id", filter=Q(status=Ticket.Status.REJECTED)),
        closed=Count("id", filter=Q(status__in=DONE_STATUSES)),
    )
    recent = (
        tickets.select_related("course", "problem_type", "teacher__user")
        .order_by("-created_at")[:5]
    )
    notifications = Notification.objects.filter(user=request.user).order_by(
        "-created_at"
    )[:5]
    unread = Notification.objects.filter(
        user=request.user, is_read=False
    ).count()
    return render(
        request,
        "partials/student_home.html",
        {
            "stats": stats,
            "recent": recent,
            "notifications": notifications,
            "unread_notifications": unread,
        },
    )


@spa_page
@student_required
def student_feed(request):
    """
    Fragment « Mes requêtes » : recherche `q` (n° de suivi, objet, catégorie,
    description, UE), filtre `status` (liste CSV possible), filtres de date
    `date_from`/`date_to`, tri `sort`, pagination.
    """
    tickets = Ticket.objects.filter(student=request.student).select_related(
        "course", "problem_type", "teacher__user"
    )

    query = (request.GET.get("q") or "").strip()
    if query:
        tickets = tickets.filter(
            Q(subject__icontains=query)
            | Q(description__icontains=query)
            | Q(problem_type__name__icontains=query)
            | Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
            # N° de suivi = 8 premiers caractères de l'UUID (minuscules).
            | Q(id__startswith=query.lower())
        )

    status = (request.GET.get("status") or "").strip()
    active_statuses = [
        value
        for value in (piece.strip() for piece in status.split(","))
        if value in Ticket.Status.values
    ]
    if active_statuses:
        tickets = tickets.filter(status__in=active_statuses)

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    if date_from:
        tickets = tickets.filter(created_at__date__gte=date_from)
    if date_to:
        tickets = tickets.filter(created_at__date__lte=date_to)

    sort = (request.GET.get("sort") or "").strip()
    if sort not in FEED_SORTS:
        sort = FEED_DEFAULT_SORT
    tickets = tickets.order_by(FEED_SORTS[sort])

    paginator = Paginator(tickets, FEED_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    # Querystring des filtres actifs (réutilisée par la pagination).
    filter_qs = urlencode(
        {
            key: value
            for key, value in (
                ("q", query),
                ("status", ",".join(active_statuses)),
                ("date_from", date_from),
                ("date_to", date_to),
                ("sort", sort if sort != FEED_DEFAULT_SORT else ""),
            )
            if value
        }
    )

    return render(
        request,
        "partials/student_feed.html",
        {
            "page_obj": page,
            "tickets": page.object_list,
            "query": query,
            "active_status": ",".join(active_statuses),
            "status_choices": Ticket.Status.choices,
            "date_from": date_from,
            "date_to": date_to,
            "sort": sort,
            "sort_choices": (
                ("created_desc", _("Plus récentes")),
                ("created_asc", _("Plus anciennes")),
                ("updated_desc", _("Dernière mise à jour")),
            ),
            "filter_qs": filter_qs,
            "total_count": paginator.count,
        },
    )


# Étapes visibles du parcours étudiant (A4 : « étape actuelle »).
TRACKING_STEPS = (
    ("sent", _("Envoyée")),
    ("received", _("Reçue")),
    ("processing", _("En cours de traitement")),
    ("decision", _("Décision")),
)
STEP_BY_STATUS = {
    Ticket.Status.SENT: 0,
    Ticket.Status.RECEIVED: 1,
    Ticket.Status.PROCESSING: 2,
    Ticket.Status.MORE_INFO: 2,
    Ticket.Status.RESOLVED: 3,
    Ticket.Status.REJECTED: 3,
}


@spa_page
@student_required
def student_ticket_detail(request, pk):
    """Suivi d'une requête appartenant à l'étudiant connecté (sinon 404)."""
    ticket = (
        Ticket.objects.filter(pk=pk, student=request.student)
        .select_related(
            "course",
            "problem_type",
            "problem_type__service",
            "assigned_service",
            "teacher__user",
            "student__user",
        )
        .prefetch_related("status_history__actor", "comments__author", "attachments__config")
        .first()
    )
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )

    # Réponses aux champs dynamiques, libellés depuis le snapshot figé.
    answered_fields = []
    labels = {
        field.get("key"): field.get("label")
        for field in (ticket.config_snapshot or {}).get("fields", [])
        if field.get("key")
    }
    for key, value in (ticket.form_data or {}).items():
        if value in ("", None, False):
            continue
        if isinstance(value, bool):
            value = _("Oui") if value else _("Non")
        answered_fields.append({"label": labels.get(key, key), "value": value})

    return render(
        request,
        "partials/student_ticket_detail.html",
        {
            "ticket": ticket,
            # Échanges publics uniquement (les notes internes sont filtrées serveur).
            "comments": [c for c in ticket.comments.all() if not c.is_internal],
            "answered_fields": answered_fields,
            "steps": TRACKING_STEPS,
            "current_step": STEP_BY_STATUS.get(ticket.status, 0),
            "service": ticket.assigned_service or ticket.problem_type.service,
        },
    )


@require_POST
@student_required
def student_reply(request):
    """
    Réponse de l'étudiant à une demande d'informations complémentaires.

    Crée un `TicketComment` (avec éventuel fichier joint : le document demandé
    par l'enseignant) puis fait muter MORE_INFO → PROCESSING (l'enseignant
    retrouve la requête en cours d'analyse dans sa boîte et consulte le fichier).
    """
    ticket_id = request.POST.get("ticket_id")
    body = (request.POST.get("body") or "").strip()
    uploaded = request.FILES.get("file")

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
    # Fichier joint facultatif : mêmes frontières que la création de ticket
    # (whitelist d'extensions + poids max, §5.3).
    if uploaded is not None:
        name = getattr(uploaded, "name", "") or ""
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if extension not in settings.ALLOWED_UPLOAD_EXTENSIONS:
            return JsonResponse(
                {
                    "status": "error",
                    "message": str(
                        _(
                            "Format de fichier non autorisé (autorisés : %(exts)s)."
                        )
                        % {"exts": ", ".join(settings.ALLOWED_UPLOAD_EXTENSIONS)}
                    ),
                    "errors": {"file": str(_("Format non autorisé."))},
                },
                status=400,
            )
        if uploaded.size > settings.MAX_UPLOAD_SIZE:
            return JsonResponse(
                {
                    "status": "error",
                    "message": str(
                        _("Fichier trop volumineux (max %(mb)s Mo).")
                        % {"mb": settings.MAX_UPLOAD_SIZE // (1024 * 1024)}
                    ),
                    "errors": {"file": str(_("Fichier trop volumineux."))},
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

    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=body,
        file=uploaded,
        file_name=(uploaded.name if uploaded else ""),
    )
    try:
        apply_status(
            ticket,
            Ticket.Status.PROCESSING,
            actor=request.user,
            actor_role=TicketStatusHistory.ActorRole.STUDENT,
            note=str(_("Réponse fournie par l'étudiant.")),
            notification_title=str(_("Réponse de l'étudiant")),
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
