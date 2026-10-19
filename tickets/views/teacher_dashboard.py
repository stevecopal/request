"""
Espace enseignant — tickets (ARCHITECTURE §7.3, Prompt 14 + espace complet).

  * `teacher_home`       : tableau de bord (vue d'ensemble reçues / en attente /
    en cours / terminées, nouvelles requêtes, notifications non lues).
  * `teacher_inbox`      : boîte de réception — recherche, filtres (statut, date,
    motif, faculté, département, cours autorisés), pagination. L'acquittement
    (SENT → RECEIVED) est un acte explicite de l'enseignant (bouton « Reçu »).
  * `teacher_inbox_list` : fragment « liste seule » — cible de rafraîchissement
    temps réel sans perdre les filtres ni le panneau de détail.
  * `ticket_detail`      : fiche détaillée (identité académique autorisée, motif,
    cours, description, pièces, échanges, historique) — propriétaire étudiant ou
    enseignant assigné, sinon 403. Les actions de décision ne sont rendues qu'à
    l'enseignant assigné (`can_decide`).
  * `download_attachment`: service de fichier protégé, consultation inline
    (pdf/images) ou téléchargement forcé.

Règle anti-falsification (IDOR) : tout queryset part de `request.teacher` — un
identifiant de profil n'est jamais lu côté client, et les tickets d'un autre
enseignant renvoient 404/403 (jamais de 200 partiel).
"""

import uuid as uuid_lib
from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import login_required_json, teacher_required
from accounts.spa import spa_page
from accounts.models import Department, Faculty, Notification, Teacher
from core_scolarite.models import Course, ProblemType, Service, ServiceAssignment
from core_scolarite.services import metrics
from core_scolarite.services.decision_rights import may_decide
from tickets.models import (
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketStatusHistory,
    TicketTransfer,
)

INBOX_PAGE_SIZE = 10

# Priorité d'affichage : non traitées d'abord.
STATUS_PRIORITY = Case(
    When(status=Ticket.Status.SENT, then=Value(0)),
    When(status=Ticket.Status.RECEIVED, then=Value(1)),
    When(status=Ticket.Status.MORE_INFO, then=Value(2)),
    When(status=Ticket.Status.PROCESSING, then=Value(3)),
    When(status=Ticket.Status.REJECTED, then=Value(4)),
    When(status=Ticket.Status.RESOLVED, then=Value(5)),
    output_field=IntegerField(),
)

# Statuts regroupés pour la vue d'ensemble (§ tableau de bord).
IN_PROGRESS_STATUSES = (Ticket.Status.PROCESSING, Ticket.Status.MORE_INFO)
DONE_STATUSES = (Ticket.Status.RESOLVED, Ticket.Status.REJECTED)

# Types MIME autorisés pour la consultation inline (déjà validés à l'upload).
INLINE_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _parse_uuid(raw):
    """UUID fourni par le client, ou None si absent/invalide (jamais d'erreur 500)."""
    if not raw:
        return None
    try:
        return uuid_lib.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_date(raw):
    """Date ISO (AAAA-MM-JJ) fournie par le client, ou None si invalide."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _teacher_service_ids(teacher):
    """Services actifs dont l'enseignant est membre (transmissions B6)."""
    return ServiceAssignment.objects.filter(
        user=teacher.user, is_active=True
    ).values_list("service_id", flat=True)


def _teacher_scope(teacher):
    """Périmètre strict de l'enseignant.

    Deux et seulement deux sources d'accès :
      * il est l'enseignant **assigné** du dossier ;
      * le dossier a été **transmis à un service** dont il est membre actif.
    Aucun filtre « département » ou « faculté » n'élargit implicitement
    l'accès : les permissions restent explicites.
    """
    return (
        Ticket.objects.filter(
            Q(teacher=teacher) | Q(assigned_service_id__in=_teacher_service_ids(teacher))
        )
        .distinct()
    )


def _teacher_can_access_ticket(teacher, ticket) -> bool:
    """Contrôle objet (jamais uniquement un queryset) pour une fiche."""
    if ticket.teacher_id == teacher.id:
        return True
    if not ticket.assigned_service_id:
        return False
    return ServiceAssignment.objects.filter(
        service_id=ticket.assigned_service_id,
        user=teacher.user,
        is_active=True,
    ).exists()


def _sla_flags(tickets, university):
    """(ids en retard, ids proches de l'échéance) pour la liste courante."""
    overdue_ids = set()
    due_soon_ids = set()
    for ticket in tickets:
        if ticket.status not in metrics.OPEN_STATUSES:
            continue
        if metrics.is_overdue(ticket, university):
            overdue_ids.add(ticket.id)
            continue
        max_days, _, _ = metrics.thresholds(ticket, university)
        if max_days - metrics.age_days(ticket) <= 1:
            due_soon_ids.add(ticket.id)
    return overdue_ids, due_soon_ids


def _form_data_rows(ticket):
    """Réponses dynamiques lisibles (libellés figés dans le snapshot)."""
    snapshot = ticket.config_snapshot or {}
    labels = {
        field.get("key"): field.get("label") or field.get("key")
        for field in snapshot.get("fields", [])
        if field.get("key")
    }
    rows = []
    for key, value in (ticket.form_data or {}).items():
        if value in ("", None, []):
            continue
        if isinstance(value, bool):
            value = str(_("Oui")) if value else str(_("Non"))
        rows.append({"label": labels.get(key, key), "value": value})
    return rows


def _allowed_courses(teacher):
    """Cours autorisés pour l'enseignant : titulaire OU département rattaché."""
    return (
        Course.objects.filter(
            Q(primary_instructor=teacher) | Q(department=teacher.department)
        )
        .distinct()
        .order_by("code")
    )


def _apply_teacher_filters(request, tickets):
    """
    Applique la chaîne de filtres de la boîte : recherche `q`, statut, motif
    (problem_type), faculté/département de l'étudiant, cours autorisé et plage
    de dates sur `created_at`. Renvoie (queryset, dict des filtres actifs).
    """
    active = {}

    query = (request.GET.get("q") or "").strip()
    if query:
        active["q"] = query
        tickets = tickets.filter(
            Q(subject__icontains=query)
            | Q(description__icontains=query)
            | Q(problem_type__name__icontains=query)
            | Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
            | Q(student__user__first_name__icontains=query)
            | Q(student__user__last_name__icontains=query)
            | Q(student__registration_number__icontains=query)
            # N° de suivi = 8 premiers caractères de l'UUID (minuscules).
            | Q(id__startswith=query.lower())
        )

    # Statut : valeur unique ou liste CSV (deep-links du tableau de bord).
    status = (request.GET.get("status") or "").strip()
    active_statuses = [
        value
        for value in (piece.strip() for piece in status.split(","))
        if value in Ticket.Status.values
    ]
    if active_statuses:
        active["status"] = ",".join(active_statuses)
        tickets = tickets.filter(status__in=active_statuses)

    problem_type_id = _parse_uuid(request.GET.get("problem_type"))
    if problem_type_id:
        active["problem_type"] = str(problem_type_id)
        tickets = tickets.filter(problem_type_id=problem_type_id)

    faculty_id = _parse_uuid(request.GET.get("faculty"))
    if faculty_id:
        active["faculty"] = str(faculty_id)
        tickets = tickets.filter(student__faculty_id=faculty_id)

    department_id = _parse_uuid(request.GET.get("department"))
    if department_id:
        active["department"] = str(department_id)
        tickets = tickets.filter(student__department_id=department_id)

    course_id = _parse_uuid(request.GET.get("course"))
    if course_id:
        active["course"] = str(course_id)
        tickets = tickets.filter(course_id=course_id)

    date_from = _parse_date(request.GET.get("date_from"))
    if date_from:
        active["date_from"] = date_from.isoformat()
        tickets = tickets.filter(created_at__date__gte=date_from)

    date_to = _parse_date(request.GET.get("date_to"))
    if date_to:
        active["date_to"] = date_to.isoformat()
        tickets = tickets.filter(created_at__date__lte=date_to)

    return tickets, active


def _filter_context(teacher, active):
    """Options des listes déroulantes des filtres, nées du périmètre de l'enseignant."""
    base = _teacher_scope(teacher)
    problem_types = (
        ProblemType.objects.filter(tickets__in=base).distinct().order_by("name")
    )
    faculties = (
        Faculty.objects.filter(students__tickets__in=base)
        .distinct()
        .order_by("name")
    )
    departments = Department.objects.filter(students__tickets__in=base)
    if active.get("faculty"):
        departments = departments.filter(faculty_id=active["faculty"])
    departments = departments.distinct().order_by("name")
    return {
        "problem_types": problem_types,
        "faculties": faculties,
        "departments": departments,
        "allowed_courses": _allowed_courses(teacher),
        "status_choices": Ticket.Status.choices,
        "active": active,
    }


def _active_querystring(active):
    """Filtres actifs sérialisés (liens de pagination qui conservent l'état)."""
    return urlencode(active)


@spa_page
@teacher_required
def teacher_home(request):
    """
    Tableau de bord enseignant : vue d'ensemble des requêtes reçues,
    en attente, en cours et terminées + nouvelles requêtes + notifications.
    """
    tickets = _teacher_scope(request.teacher)
    university = request.teacher.university
    assigned = tickets.count()
    stats = {
        "assigned": assigned,
        "total": assigned,
        "new": tickets.filter(status=Ticket.Status.SENT).count(),
        "awaiting": tickets.filter(status=Ticket.Status.RECEIVED).count(),
        "in_progress": tickets.filter(status__in=IN_PROGRESS_STATUSES).count(),
        "done": tickets.filter(status__in=DONE_STATUSES).count(),
    }

    # Délais : calcul par dossier (les règles SLA peuvent différer selon la
    # catégorie de la requête). Le volume d'un enseignant reste faible.
    open_tickets = list(
        tickets.filter(status__in=metrics.OPEN_STATUSES).select_related(
            "problem_type", "course", "student__user", "assigned_service"
        )
    )
    overdue_tickets = []
    due_soon_tickets = []
    for ticket in open_tickets:
        max_days, _, _ = metrics.thresholds(ticket, university)
        age = metrics.age_days(ticket)
        ticket.sla_max_days = max_days
        ticket.sla_age_days = round(age, 1)
        if metrics.is_overdue(ticket, university):
            overdue_tickets.append(ticket)
            continue
        remaining = max_days - age
        if remaining <= 1:
            ticket.sla_days_left = max(0, round(remaining))
            due_soon_tickets.append(ticket)

    overdue_tickets.sort(key=lambda item: item.sla_age_days, reverse=True)
    due_soon_tickets.sort(key=lambda item: item.sla_days_left)
    stats["overdue"] = len(overdue_tickets)
    stats["due_soon"] = len(due_soon_tickets)

    recent = (
        tickets.select_related(
            "course", "problem_type", "student__user", "assigned_service"
        )
        .order_by(STATUS_PRIORITY, "-created_at")[:5]
    )
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    notifications = Notification.objects.filter(user=request.user).order_by(
        "-created_at"
    )[:5]
    return render(
        request,
        "partials/teacher_home.html",
        {
            "stats": stats,
            "recent": recent,
            "overdue_tickets": overdue_tickets[:5],
            "due_soon_tickets": due_soon_tickets[:5],
            "notifications": notifications,
            "unread_notifications": unread,
        },
    )


def _render_teacher_list(request, teacher):
    """Logique partagée inbox / liste seule : filtrage, tri, pagination."""
    tickets = _teacher_scope(teacher).select_related(
        "student__user",
        "student__faculty",
        "student__department",
        "course",
        "problem_type",
        "assigned_service",
    )
    tickets, active = _apply_teacher_filters(request, tickets)
    tickets = tickets.order_by(STATUS_PRIORITY, "-created_at")
    paginator = Paginator(tickets, INBOX_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    return page, active, paginator


@spa_page
@teacher_required
def teacher_inbox(request):
    """
    Fragment « Boîte de réception » (enseignant) : filtres + liste + panneau
    de détail. Aucune mutation automatique : c'est l'enseignant qui acquitte
    chaque requête (SENT → RECEIVED) avec le bouton « Reçu », puis la met en
    charge — l'étudiant est notifié à chaque étape.
    """
    page, active, paginator = _render_teacher_list(request, request.teacher)
    overdue_ids, due_soon_ids = _sla_flags(
        page.object_list, request.teacher.university
    )
    context = {
        "page_obj": page,
        "tickets": page.object_list,
        "total_count": paginator.count,
        "inbox_list_url": reverse("tickets:teacher_inbox_list"),
        "active_qs": _active_querystring(active),
        "overdue_ids": overdue_ids,
        "due_soon_ids": due_soon_ids,
    }
    context.update(_filter_context(request.teacher, active))
    return render(request, "partials/teacher_inbox.html", context)


@teacher_required
def teacher_inbox_list(request):
    """
    Fragment « liste seule » de la boîte : cible de rafraîchissement temps
    réel (nouvelle requête, re-classement après décision) sans perdre les
    filtres ni le reste de la page.
    """
    page, active, paginator = _render_teacher_list(request, request.teacher)
    overdue_ids, due_soon_ids = _sla_flags(
        page.object_list, request.teacher.university
    )
    return render(
        request,
        "partials/teacher_inbox_list.html",
        {
            "page_obj": page,
            "tickets": page.object_list,
            "total_count": paginator.count,
            "active": active,
            "active_qs": _active_querystring(active),
            "overdue_ids": overdue_ids,
            "due_soon_ids": due_soon_ids,
        },
    )


def _get_accessible_ticket(request, pk):
    """Renvoie le ticket si l'utilisateur y a droit, sinon (None, réponse d'erreur)."""
    ticket = (
        Ticket.objects.select_related(
            "student__user",
            "student__faculty",
            "student__department",
            "teacher__user",
            "course",
            "problem_type",
            "assigned_service",
        )
        .prefetch_related(
            "status_history__actor",
            "attachments__config",
            "comments__author",
            "transfers__from_teacher__user",
            "transfers__to_teacher__user",
            "transfers__to_service",
            "transfers__actor",
        )
        .filter(pk=pk)
        .first()
    )
    if ticket is None:
        return None, JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )

    student_profile = getattr(request.user, "student_profile", None)
    teacher_profile = getattr(request.user, "teacher_profile", None)
    if student_profile and ticket.student_id == student_profile.id:
        return ticket, None
    if teacher_profile and _teacher_can_access_ticket(teacher_profile, ticket):
        return ticket, None
    return None, JsonResponse(
        {"status": "error", "message": str(_("Accès non autorisé."))}, status=403
    )


def _teacher_ticket_or_error(request, raw_id):
    """Ticket accessible à l'enseignant connecté, ou réponse JSON d'erreur."""
    ticket_id = _parse_uuid(raw_id)
    if ticket_id is None:
        return None, JsonResponse(
            {"status": "error", "message": str(_("Identifiant de requête invalide."))},
            status=400,
        )
    return _get_accessible_ticket(request, ticket_id)


@teacher_required
def teacher_decision_modal(request):
    """Fragment de la modale de décision (Accepter / Rejeter / Infos supplémentaires).

    Le droit est vérifié par `may_decide` : enseignant assigné, ou périmètre
    élargi explicitement par une règle de workflow. Un simple membre du
    service sans règle de décision ne peut donc pas clôturer le dossier.
    """
    ticket_id = request.GET.get("ticket_id")
    target = request.GET.get("target")
    allowed_targets = [Ticket.Status.RESOLVED, Ticket.Status.REJECTED]
    if settings.ENABLE_TEACHER_MORE_INFO:
        allowed_targets.append(Ticket.Status.MORE_INFO)
    if target not in allowed_targets:
        return JsonResponse(
            {"status": "error", "message": str(_("Cible de décision invalide."))},
            status=400,
        )
    ticket, error = _teacher_ticket_or_error(request, ticket_id)
    if error:
        return error
    if not may_decide(request.user, ticket, new_status=target):
        return JsonResponse(
            {"status": "error", "message": str(_("Action non autorisée."))}, status=403
        )
    return render(
        request,
        "modals/teacher_decision.html",
        {"ticket": ticket, "target": target},
    )


@spa_page
@login_required_json
def ticket_detail(request, pk):
    """Fiche détaillée d'un ticket (propriétaire ou enseignant autorisé).

    * `is_teacher_view` : l'utilisateur est l'enseignant assigné ou un membre
      actif du service destinataire.
    * `can_decide` : uniquement si `may_decide` l'autorise (enseignant assigné
      ou périmètre de workflow) — jamais déduit du seul rôle « enseignant ».
      Seul `can_decide` affiche les boutons Reçu / Prise en charge / Infos /
      Accepter / Rejeter et le transfert (réaffectation par l'enseignant).
    * côté étudiant, les commentaires internes sont filtrés côté serveur.
    """
    ticket, error = _get_accessible_ticket(request, pk)
    if error:
        return error
    teacher_profile = getattr(request.user, "teacher_profile", None)
    is_teacher_view = bool(
        teacher_profile is not None
        and _teacher_can_access_ticket(teacher_profile, ticket)
    )
    can_decide = bool(
        is_teacher_view and may_decide(request.user, ticket)
    )
    comments = (
        ticket.comments.all()
        if is_teacher_view
        else ticket.comments.filter(is_internal=False)
    )

    sla = None
    if is_teacher_view:
        university = teacher_profile.university
        max_days, blocked_days, _policy = metrics.thresholds(ticket, university)
        age = metrics.age_days(ticket)
        sla = {
            "overdue": metrics.is_overdue(ticket, university),
            "blocked": metrics.is_blocked(ticket, university),
            "max_days": max_days,
            "blocked_days": blocked_days,
            "age_days": round(age, 1),
            "days_left": max(0, round(max_days - age, 1)),
        }

    return render(
        request,
        "partials/teacher_ticket_detail.html",
        {
            "ticket": ticket,
            "comments": comments,
            "is_teacher_view": is_teacher_view,
            "can_decide": can_decide,
            "can_transfer": can_decide and ticket.is_open,
            "more_info_enabled": settings.ENABLE_TEACHER_MORE_INFO,
            "sla": sla,
            "form_data_rows": _form_data_rows(ticket),
        },
    )


@teacher_required
def teacher_transfer_modal(request):
    """Modale de transmission (B6) : intervenant et/ou service destinataire."""
    ticket, error = _teacher_ticket_or_error(request, request.GET.get("ticket_id"))
    if error:
        return error
    if not ticket.is_open:
        return JsonResponse(
            {"status": "error", "message": str(_("Ce dossier est déjà clôturé."))},
            status=400,
        )
    university = (
        ticket.student.faculty.university
        if ticket.student.faculty_id
        else request.teacher.university
    )
    services = Service.objects.filter(
        university=university, is_active=True
    ).order_by("name")
    teachers = (
        Teacher.objects.filter(faculty__university=university)
        .exclude(pk=request.teacher.pk)
        .select_related("user", "department")
        .order_by("user__last_name", "user__first_name")
    )
    return render(
        request,
        "modals/teacher_transfer.html",
        {
            "ticket": ticket,
            "services": services,
            "teachers": teachers,
        },
    )


@require_POST
@teacher_required
def teacher_transfer(request):
    """Transmet un dossier à un autre enseignant et/ou à un service, avec motif.

    Seul l'enseignant assigné peut réaffecter (jamais l'admin) : une
    transmission à un intervenant change l'enseignant assigné (notifié), une
    transmission à un service ouvre le dossier à ses membres actifs.
    """
    ticket, error = _teacher_ticket_or_error(request, request.POST.get("ticket_id"))
    if error:
        return error
    # Seul l'enseignant assigné réaffecte (jamais l'admin, jamais un service seul).
    from core_scolarite.services.decision_rights import _is_assigned_teacher

    if not _is_assigned_teacher(request.user, ticket):
        return JsonResponse(
            {"status": "error", "message": str(_("Action non autorisée."))}, status=403
        )
    if not ticket.is_open:
        return JsonResponse(
            {"status": "error", "message": str(_("Ce dossier est déjà clôturé."))},
            status=400,
        )

    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        return JsonResponse(
            {
                "status": "error",
                "message": str(_("Le motif de la transmission est obligatoire.")),
                "errors": {"reason": str(_("Champ obligatoire."))},
            },
            status=400,
        )

    to_teacher_id = _parse_uuid(request.POST.get("to_teacher"))
    to_service_id = _parse_uuid(request.POST.get("to_service"))
    if to_teacher_id is None and to_service_id is None:
        return JsonResponse(
            {
                "status": "error",
                "message": str(
                    _("Choisissez un intervenant ou un service destinataire.")
                ),
            },
            status=400,
        )

    university = (
        ticket.student.faculty.university
        if ticket.student.faculty_id
        else request.teacher.university
    )
    to_teacher = None
    to_service = None
    if to_teacher_id is not None:
        to_teacher = (
            Teacher.objects.select_related("user", "faculty")
            .filter(pk=to_teacher_id, faculty__university=university)
            .first()
        )
        if to_teacher is None:
            return JsonResponse(
                {
                    "status": "error",
                    "message": str(_("Intervenant destinataire introuvable.")),
                },
                status=400,
            )
    if to_service_id is not None:
        to_service = Service.objects.filter(
            pk=to_service_id, university=university, is_active=True
        ).first()
        if to_service is None:
            return JsonResponse(
                {"status": "error", "message": str(_("Service destinataire introuvable."))},
                status=400,
            )

    if to_teacher is not None and to_teacher.id == ticket.teacher_id and to_service is None:
        return JsonResponse(
            {
                "status": "error",
                "message": str(_("Ce dossier est déjà assigné à cet intervenant.")),
            },
            status=400,
        )

    with transaction.atomic():
        locked = (
            Ticket.objects.select_for_update()
            .select_related("teacher__user", "student__user", "problem_type")
            .get(pk=ticket.pk)
        )
        from_teacher = locked.teacher
        if to_teacher is not None:
            locked.teacher = to_teacher
        if to_service is not None:
            locked.assigned_service = to_service
        elif to_teacher is not None:
            # Transmission directe à un intervenant : la file du service
            # précédent ne doit plus élargir l'accès au dossier.
            locked.assigned_service = None

        target_label = " · ".join(
            item
            for item in (
                to_teacher.full_name if to_teacher is not None else "",
                to_service.name if to_service is not None else "",
            )
            if item
        )
        locked._actor_user_id = request.user.id
        locked._notification_title = (
            _("Nouvelle affectation")
            if to_teacher is not None
            else _("Dossier transmis à un service")
        )
        locked.save(update_fields=["teacher", "assigned_service", "updated_at"])

        TicketTransfer.objects.create(
            ticket=locked,
            from_teacher=from_teacher,
            to_teacher=to_teacher,
            to_service=to_service,
            reason=reason,
            actor=request.user,
        )
        TicketStatusHistory.objects.create(
            ticket=locked,
            from_status=locked.status,
            to_status=locked.status,
            actor=request.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            note=str(_("Transmis à %(target)s — %(reason)s"))
            % {"target": target_label, "reason": reason},
        )

        # Notifications de transmission (centre enseignant) : l'ancien garde une
        # trace même s'il perd l'accès, le nouvel enseignant est notifié de sa
        # nouvelle affectation, et l'étudiant suit la réaffectation de sa requête.
        if from_teacher.user_id != request.user.id:
            Notification.objects.create(
                user=from_teacher.user,
                ticket=locked,
                title=str(_("Dossier transféré")),
                body=f"{locked.problem_type} — {target_label}",
            )
        if to_teacher is not None and to_teacher.user_id != request.user.id:
            Notification.objects.create(
                user=to_teacher.user,
                ticket=locked,
                title=str(_("Nouvelle affectation")),
                body=f"{locked.problem_type} — {target_label}",
            )
        if locked.student_id and locked.student.user_id != request.user.id:
            Notification.objects.create(
                user=locked.student.user,
                ticket=locked,
                title=str(_("Requête réaffectée")),
                body=f"{locked.problem_type} — {target_label}",
            )

    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Dossier transmis à %(target)s."))
            % {"target": target_label},
            "ticket": {
                "id": str(locked.id),
                "status": locked.status,
                "status_label": locked.status_label,
            },
        }
    )


@login_required_json
def download_attachment(request, pk):
    """
    Service de fichier protégé d'une pièce jointe (contrôle d'appartenance).

    `?inline=1` demande la consultation dans le navigateur (pdf/images) — le
    Content-Type reste borné à la whitelist d'extensions validées à l'upload.
    """
    attachment = get_object_or_404(
        TicketAttachment.objects.select_related(
            "ticket__student", "ticket__teacher", "config"
        ),
        pk=pk,
    )
    ticket, error = _get_accessible_ticket(request, attachment.ticket_id)
    if error:
        return error

    extension = attachment.file_extension
    inline = request.GET.get("inline") == "1" and extension in INLINE_CONTENT_TYPES

    response = FileResponse(attachment.file.open("rb"))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=0"
    if inline:
        response["Content-Type"] = INLINE_CONTENT_TYPES[extension]
        response["Content-Disposition"] = 'inline; filename="justificatif.%s"' % extension
    else:
        response["Content-Type"] = "application/octet-stream"
        response["Content-Disposition"] = (
            f'attachment; filename="{attachment.file.name.rsplit("/", 1)[-1]}"'
        )
    return response


@login_required_json
def download_comment_file(request, pk):
    """
    Service de fichier protégé du fichier joint à un échange (commentaire).

    Cas d'usage : réponse de l'étudiant à une demande d'informations
    complémentaires — il dépose le document demandé, l'enseignant assigné le
    consulte (`?inline=1`) ou le télécharge. Même contrôle d'appartenance que
    les pièces jointes (propriétaire étudiant ou enseignant autorisé).
    """
    comment = get_object_or_404(
        TicketComment.objects.select_related("ticket"),
        pk=pk,
    )
    ticket, error = _get_accessible_ticket(request, comment.ticket_id)
    if error:
        return error
    if not comment.file:
        return JsonResponse(
            {"status": "error", "message": str(_("Aucun fichier joint."))}, status=404
        )

    extension = comment.file_extension
    inline = request.GET.get("inline") == "1" and extension in INLINE_CONTENT_TYPES

    response = FileResponse(comment.file.open("rb"))
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=0"
    if inline:
        response["Content-Type"] = INLINE_CONTENT_TYPES[extension]
        response["Content-Disposition"] = 'inline; filename="echange.%s"' % extension
    else:
        response["Content-Type"] = "application/octet-stream"
        # Nom d'origine nettoyé pour l'en-tête (guillemets/retours ligne interdits).
        display_name = (
            comment.file_basename.replace('"', "").replace("\r", "").replace("\n", "")
            or f"echange.{extension or 'bin'}"
        )
        response["Content-Disposition"] = f'attachment; filename="{display_name}"'
    return response
