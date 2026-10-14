"""
Espace enseignant — tickets (ARCHITECTURE §7.3, Prompt 14 + espace complet).

  * `teacher_home`       : tableau de bord (vue d'ensemble reçues / en attente /
    en cours / terminées, nouvelles requêtes, notifications non lues).
  * `teacher_inbox`      : boîte de réception — recherche, filtres (statut, date,
    motif, faculté, département, cours autorisés), pagination. Les tickets SENT
    sont acquittés automatiquement (→ RECEIVED) à l'ouverture de la boîte.
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
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from accounts.decorators import login_required_json, teacher_required
from accounts.models import Department, Faculty, Notification
from core_scolarite.models import Course, ProblemType
from tickets.models import Ticket, TicketAttachment, TicketStatusHistory
from tickets.services.status_machine import apply_status

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


def _teacher_scope(teacher):
    """Périmètre universitaire strict : uniquement les tickets assignés."""
    return Ticket.objects.filter(teacher=teacher)


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
            Q(description__icontains=query)
            | Q(problem_type__name__icontains=query)
            | Q(course__code__icontains=query)
            | Q(course__name__icontains=query)
            | Q(student__user__first_name__icontains=query)
            | Q(student__user__last_name__icontains=query)
            | Q(student__registration_number__icontains=query)
        )

    status = (request.GET.get("status") or "").strip()
    if status in Ticket.Status.values:
        active["status"] = status
        tickets = tickets.filter(status=status)

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
        Faculty.objects.filter(students__tickets__teacher=teacher)
        .distinct()
        .order_by("name")
    )
    departments = Department.objects.filter(students__tickets__teacher=teacher)
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


@teacher_required
def teacher_home(request):
    """
    Tableau de bord enseignant : vue d'ensemble des requêtes reçues,
    en attente, en cours et terminées + nouvelles requêtes + notifications.
    """
    tickets = _teacher_scope(request.teacher)
    stats = {
        "total": tickets.count(),
        "new": tickets.filter(status=Ticket.Status.SENT).count(),
        "awaiting": tickets.filter(status=Ticket.Status.RECEIVED).count(),
        "in_progress": tickets.filter(status__in=IN_PROGRESS_STATUSES).count(),
        "done": tickets.filter(status__in=DONE_STATUSES).count(),
    }
    recent = (
        tickets.select_related("course", "problem_type", "student__user")
        .order_by(STATUS_PRIORITY, "-created_at")[:5]
    )
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return render(
        request,
        "partials/teacher_home.html",
        {"stats": stats, "recent": recent, "unread_notifications": unread},
    )


def _render_teacher_list(request, teacher):
    """Logique partagée inbox / liste seule : filtrage, tri, pagination."""
    tickets = _teacher_scope(teacher).select_related(
        "student__user", "course", "problem_type"
    )
    tickets, active = _apply_teacher_filters(request, tickets)
    tickets = tickets.order_by(STATUS_PRIORITY, "-created_at")
    paginator = Paginator(tickets, INBOX_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    return page, active, paginator


@teacher_required
def teacher_inbox(request):
    """
    Fragment « Boîte de réception » (enseignant) : filtres + liste + panneau
    de détail. Les tickets SENT sont acquittés automatiquement (→ RECEIVED)
    dès l'ouverture — le signal temps réel notifie l'étudiant.
    """
    # Acquittement automatique : SENT → RECEIVED à l'ouverture de la boîte.
    for ticket in _teacher_scope(request.teacher).filter(status=Ticket.Status.SENT):
        apply_status(
            ticket,
            Ticket.Status.RECEIVED,
            actor=request.teacher.user,
            actor_role=TicketStatusHistory.ActorRole.TEACHER,
            note=str(_("Acquittement automatique à l'ouverture de la boîte.")),
        )

    page, active, paginator = _render_teacher_list(request, request.teacher)
    context = {
        "page_obj": page,
        "tickets": page.object_list,
        "total_count": paginator.count,
        "inbox_list_url": reverse("tickets:teacher_inbox_list"),
        "active_qs": _active_querystring(active),
    }
    context.update(_filter_context(request.teacher, active))
    return render(request, "partials/teacher_inbox.html", context)


@teacher_required
def teacher_inbox_list(request):
    """
    Fragment « liste seule » de la boîte : cible de rafraîchissement temps
    réel (nouvelle requête, re-classement après décision) sans perdre les
    filtres ni le reste de la page. Pas d'acquittement ici (déjà fait au
    chargement du fragment complet).
    """
    page, active, paginator = _render_teacher_list(request, request.teacher)
    return render(
        request,
        "partials/teacher_inbox_list.html",
        {
            "page_obj": page,
            "tickets": page.object_list,
            "total_count": paginator.count,
            "active": active,
            "active_qs": _active_querystring(active),
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
        )
        .prefetch_related(
            "status_history__actor", "attachments__config", "comments__author"
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
    if teacher_profile and ticket.teacher_id == teacher_profile.id:
        return ticket, None
    return None, JsonResponse(
        {"status": "error", "message": str(_("Accès non autorisé."))}, status=403
    )


@teacher_required
def teacher_decision_modal(request):
    """Fragment de la modale de décision (Valider / Rejeter / Plus d'infos)."""
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
    ticket = Ticket.objects.filter(pk=ticket_id, teacher=request.teacher).first()
    if ticket is None:
        return JsonResponse(
            {"status": "error", "message": str(_("Requête introuvable."))}, status=404
        )
    return render(
        request,
        "modals/teacher_decision.html",
        {"ticket": ticket, "target": target},
    )


@login_required_json
def ticket_detail(request, pk):
    """Fragment de détail d'un ticket (propriétaire ou enseignant assigné).

    `can_decide` est True uniquement pour l'enseignant assigné : seules ses
    actions de décision sont rendues (jamais chez l'étudiant propriétaire,
    qui ne dispose que du suivi).
    """
    ticket, error = _get_accessible_ticket(request, pk)
    if error:
        return error
    teacher_profile = getattr(request.user, "teacher_profile", None)
    can_decide = bool(
        teacher_profile is not None and ticket.teacher_id == teacher_profile.id
    )
    return render(
        request,
        "partials/teacher_ticket_detail.html",
        {
            "ticket": ticket,
            "more_info_enabled": settings.ENABLE_TEACHER_MORE_INFO,
            "can_decide": can_decide,
        },
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
