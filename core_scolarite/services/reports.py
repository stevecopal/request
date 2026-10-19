"""
Rapports & exports (C5) — statistiques serveur, CSV et PDF.

Deux niveaux :
  * `build_stats(...)`  → indicateurs agrégés affichés sur l'écran
    « Statistiques & rapports » (et réutilisables ailleurs) ;
  * `dataset(...)`      → lignes d'export pour un jeu donné, exportées en
    CSV (`csv_response`) ou en PDF via reportlab (`pdf_response`).

Chaque export est tracé au journal d'audit (`EXPORT`).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, time, timedelta

from django.db.models import Avg, Count, F, Q
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Faculty  # noqa: F401  (réexporté pour les vues de rapports)
from core_scolarite.models import AuditLog
from core_scolarite.services import audit as audit_service
from core_scolarite.services import metrics as metrics_service
from tickets.models import Ticket, TicketStatusHistory

__all__ = [
    "KINDS",
    "parse_filters",
    "tickets_queryset",
    "build_stats",
    "dataset",
    "csv_response",
    "pdf_response",
]

KINDS = ("synthese", "requetes", "utilisateurs", "journal", "historique")

MAX_CSV_ROWS = 10000
MAX_PDF_ROWS = 400

MONTHS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

OPEN_STATUSES = (
    Ticket.Status.SENT,
    Ticket.Status.RECEIVED,
    Ticket.Status.PROCESSING,
    Ticket.Status.MORE_INFO,
)


# --------------------------------------------------------------------------- #
# Filtres & périmètre
# --------------------------------------------------------------------------- #

def parse_filters(request, university=None) -> dict:
    """Lit `ReportFilterForm` depuis la query-string (ou le corps POST)."""
    from core_scolarite.forms import ReportFilterForm

    params = request.POST if request.method == "POST" and request.POST else request.GET
    form = ReportFilterForm(params, university=university)
    filters: dict = {
        "form": form,
        "date_from": None,
        "date_to": None,
        "faculty": None,
        "department": None,
        "problem_type": None,
    }
    if not form.is_valid():
        return filters
    cleaned = form.cleaned_data
    if cleaned.get("date_from"):
        filters["date_from"] = timezone.make_aware(
            datetime.combine(cleaned["date_from"], time.min)
        )
    if cleaned.get("date_to"):
        end = timezone.make_aware(
            datetime.combine(cleaned["date_to"], time.max.replace(microsecond=999999))
        )
        filters["date_to"] = end
    filters["faculty"] = cleaned.get("faculty")
    filters["department"] = cleaned.get("department")
    filters["problem_type"] = cleaned.get("problem_type")
    return filters


def _in_university(qs, university):
    if university is None:
        return qs
    return qs.filter(
        Q(student__faculty__university=university)
        | Q(student__faculty__isnull=True)
        | Q(student__isnull=True)
    )


def tickets_queryset(filters: dict, university=None, select_related: bool = True) -> Ticket:
    qs = Ticket.objects.all()
    if select_related:
        qs = qs.select_related(
            "student__user",
            "student__faculty",
            "student__department",
            "teacher__user",
            "course",
            "problem_type",
        )
    qs = _in_university(qs, university)
    if filters.get("date_from"):
        qs = qs.filter(created_at__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__lte=filters["date_to"])
    if filters.get("faculty"):
        qs = qs.filter(student__faculty=filters["faculty"])
    if filters.get("department"):
        qs = qs.filter(student__department=filters["department"])
    if filters.get("problem_type"):
        qs = qs.filter(problem_type=filters["problem_type"])
    return qs.order_by("-created_at")


# --------------------------------------------------------------------------- #
# Statistiques agrégées
# --------------------------------------------------------------------------- #

def _pct(part, total) -> float:
    if not total:
        return 0.0
    return round(100 * part / total, 1)


def build_stats(qs, university=None) -> dict:
    """Indicateurs calculés sur un queryset de tickets déjà filtré."""
    total = qs.count()
    status_counts = dict(qs.values_list("status").annotate(c=Count("id")))
    status_labels = dict(Ticket.Status.choices)

    by_status = [
        {
            "key": key,
            "label": status_labels.get(key, key),
            "count": status_counts.get(key, 0),
            "pct": _pct(status_counts.get(key, 0), total),
        }
        for key in Ticket.Status.values
        if status_counts.get(key, 0)
    ]

    by_month = []
    for row in qs.annotate(month=TruncMonth("created_at")).values("month").annotate(
        c=Count("id")
    ).order_by("month"):
        month = row["month"]
        if month is None:
            continue
        by_month.append(
            {
                "key": month.strftime("%Y-%m"),
                "label": f"{MONTHS_FR[month.month]} {month.year}",
                "count": row["c"],
            }
        )

    by_category = [
        {"name": row["problem_type__name"], "count": row["c"]}
        for row in qs.values("problem_type__name").annotate(c=Count("id")).order_by("-c")[:10]
    ]
    by_department = [
        {"name": row["student__department__name"] or _("Sans département"), "count": row["c"]}
        for row in qs.values("student__department__name")
        .annotate(c=Count("id"))
        .order_by("-c")[:10]
    ]

    resolved = qs.filter(status=Ticket.Status.RESOLVED).count()
    rejected = qs.filter(status=Ticket.Status.REJECTED).count()
    decisions = resolved + rejected

    resolution = qs.filter(resolved_at__isnull=False).aggregate(
        avg=Avg(F("resolved_at") - F("created_at"))
    )["avg"]
    avg_hours = None
    if resolution is not None:
        avg_hours = round(resolution.total_seconds() / 3600, 1)

    open_qs = qs.filter(status__in=OPEN_STATUSES)
    overdue = open_qs.filter(metrics_service.overdue_q(university=university)).count()
    blocked = open_qs.filter(metrics_service.blocked_q(university=university)).count()

    return {
        "total": total,
        "open": sum(status_counts.get(s, 0) for s in OPEN_STATUSES),
        "resolved": resolved,
        "rejected": rejected,
        "in_progress": status_counts.get(Ticket.Status.PROCESSING, 0),
        "by_status": by_status,
        "by_month": by_month,
        "by_category": by_category,
        "by_department": by_department,
        "avg_resolution_hours": avg_hours,
        "accepted_rate": _pct(resolved, decisions),
        "rejected_rate": _pct(rejected, decisions),
        "overdue": overdue,
        "blocked": blocked,
        "escalated": qs.filter(is_escalated=True).count(),
    }


# --------------------------------------------------------------------------- #
# Jeux de données d'export
# --------------------------------------------------------------------------- #

def _users_rows(filters: dict, university=None):
    from django.contrib.auth.models import User

    qs = User.objects.select_related(
        "student_profile__faculty", "student_profile__department",
        "teacher_profile__faculty", "teacher_profile__department",
    ).order_by("username")
    if university is not None:
        qs = qs.filter(
            Q(is_superuser=True)
            | Q(is_staff=True)
            | Q(student_profile__faculty__university=university)
            | Q(teacher_profile__faculty__university=university)
        )
    if filters.get("date_from"):
        qs = qs.filter(date_joined__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(date_joined__lte=filters["date_to"])
    if filters.get("faculty"):
        faculty = filters["faculty"]
        qs = qs.filter(
            Q(student_profile__faculty=faculty) | Q(teacher_profile__faculty=faculty)
        )
    if filters.get("department"):
        department = filters["department"]
        qs = qs.filter(
            Q(student_profile__department=department) | Q(teacher_profile__department=department)
        )

    def roles(user) -> str:
        names = []
        if user.is_superuser:
            names.append(_("Superadministrateur"))
        elif user.is_staff:
            names.append(_("Personnel"))
        if hasattr(user, "student_profile"):
            names.append(_("Étudiant"))
        if hasattr(user, "teacher_profile"):
            names.append(_("Enseignant"))
        return " / ".join(names) or _("Aucun profil")

    headers = [
        _("Nom d'utilisateur"), _("Nom complet"), _("E-mail"), _("Rôles"),
        _("Faculté"), _("Département"), _("Actif"), _("Inscription"),
    ]
    rows = []
    for user in qs[:MAX_CSV_ROWS]:
        student = getattr(user, "student_profile", None)
        teacher = getattr(user, "teacher_profile", None)
        profile = student or teacher
        faculty = profile.faculty.name if profile and profile.faculty_id else "—"
        department = profile.department.name if profile and profile.department_id else "—"
        rows.append([
            user.username,
            user.get_full_name() or "—",
            user.email or "—",
            roles(user),
            faculty,
            department,
            _("Oui") if user.is_active else _("Non"),
            timezone.localtime(user.date_joined).strftime("%d/%m/%Y %H:%M"),
        ])
    return headers, rows


def _journal_rows(filters: dict, university=None):
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    if university is not None:
        qs = qs.filter(Q(university=university) | Q(university__isnull=True))
    if filters.get("date_from"):
        qs = qs.filter(created_at__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__lte=filters["date_to"])
    action_labels = dict(AuditLog.Action.choices)
    headers = [
        _("Horodatage"), _("Acteur"), _("Action"), _("Entité"),
        _("Clé"), _("Objet"), _("Changements"), _("Adresse IP"),
    ]
    rows = []
    for entry in qs[:MAX_CSV_ROWS]:
        rows.append([
            timezone.localtime(entry.created_at).strftime("%d/%m/%Y %H:%M:%S"),
            entry.actor.username if entry.actor else _("Système"),
            action_labels.get(entry.action, entry.action),
            entry.model_label,
            entry.object_pk or "—",
            entry.object_repr or "—",
            json.dumps(entry.changes, ensure_ascii=False) if entry.changes else "—",
            entry.ip or "—",
        ])
    return headers, rows


def _history_rows(filters: dict, university=None):
    qs = TicketStatusHistory.objects.select_related(
        "ticket__student__user", "actor"
    ).order_by("-created_at")
    if university is not None:
        qs = qs.filter(
            Q(ticket__student__faculty__university=university)
            | Q(ticket__student__faculty__isnull=True)
            | Q(ticket__student__isnull=True)
        )
    if filters.get("date_from"):
        qs = qs.filter(created_at__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(created_at__lte=filters["date_to"])
    if filters.get("problem_type"):
        qs = qs.filter(ticket__problem_type=filters["problem_type"])
    status_labels = dict(Ticket.Status.choices)
    headers = [
        _("Horodatage"), _("Référence"), _("De"), _("Vers"),
        _("Acteur"), _("Rôle"), _("Note"),
    ]
    rows = []
    for entry in qs[:MAX_CSV_ROWS]:
        rows.append([
            timezone.localtime(entry.created_at).strftime("%d/%m/%Y %H:%M:%S"),
            entry.ticket.short_id if entry.ticket else "—",
            status_labels.get(entry.from_status, entry.from_status) if entry.from_status else "—",
            status_labels.get(entry.to_status, entry.to_status),
            entry.actor.username if entry.actor else _("Système"),
            entry.actor_role or "—",
            (entry.note or "—").replace("\n", " ")[:200],
        ])
    return headers, rows


def _tickets_rows(filters: dict, university=None):
    qs = tickets_queryset(filters, university)
    headers = [
        _("Référence"), _("Créée le"), _("Étudiant"), _("Faculté"),
        _("Département"), _("Catégorie"), _("Enseignant"), _("Statut"),
        _("Dernière activité"), _("Âge (jours)"), _("Escalée"),
    ]
    status_labels = dict(Ticket.Status.choices)
    now = timezone.now()
    rows = []
    for ticket in qs[:MAX_CSV_ROWS]:
        student = ticket.student
        user = student.user if student else None
        faculty = student.faculty.name if student and student.faculty_id else "—"
        department = student.department.name if student and student.department_id else "—"
        rows.append([
            ticket.short_id,
            timezone.localtime(ticket.created_at).strftime("%d/%m/%Y %H:%M"),
            user.get_full_name() or (user.username if user else "—"),
            faculty,
            department,
            ticket.problem_type.name if ticket.problem_type_id else "—",
            ticket.teacher.user.get_full_name()
            if ticket.teacher_id and ticket.teacher.user
            else "—",
            status_labels.get(ticket.status, ticket.status),
            timezone.localtime(ticket.updated_at).strftime("%d/%m/%Y %H:%M")
            if ticket.updated_at else "—",
            round(metrics_service.age_days(ticket, now), 1),
            _("Oui") if ticket.is_escalated else _("Non"),
        ])
    return headers, rows


def _synthese_rows(filters: dict, university=None):
    qs = tickets_queryset(filters, university, select_related=False)
    stats = build_stats(qs, university=university)
    headers = [_("Indicateur"), _("Valeur")]
    rows = [
        [_("Requêtes (périmètre)"), stats["total"]],
        [_("Dossiers ouverts"), stats["open"]],
        [_("Dossiers en traitement"), stats["in_progress"]],
        [_("Résolus"), stats["resolved"]],
        [_("Refusés"), stats["rejected"]],
        [_("Taux d'acceptation (%)"), stats["accepted_rate"]],
        [_("Taux de refus (%)"), stats["rejected_rate"]],
        [_("En retard (SLA)"), stats["overdue"]],
        [_("Bloqués (SLA)"), stats["blocked"]],
        [_("Escaladés"), stats["escalated"]],
        [
            _("Délai moyen de résolution (h)"),
            stats["avg_resolution_hours"] if stats["avg_resolution_hours"] is not None else "—",
        ],
    ]
    for item in stats["by_category"]:
        rows.append([_("Catégorie : ") + str(item["name"]), item["count"]])
    for item in stats["by_department"]:
        rows.append([_("Département : ") + str(item["name"]), item["count"]])
    return headers, rows


def dataset(kind: str, filters: dict, university=None):
    """(titre, en-têtes, lignes) pour un jeu d'export donné."""
    builders = {
        "synthese": _synthese_rows,
        "requetes": _tickets_rows,
        "utilisateurs": _users_rows,
        "journal": _journal_rows,
        "historique": _history_rows,
    }
    if kind not in builders:
        raise ValueError(f"Jeu d'export inconnu : {kind}")
    headers, rows = builders[kind](filters, university)
    titles = {
        "synthese": _("Synthèse des indicateurs"),
        "requetes": _("Liste des requêtes"),
        "utilisateurs": _("Liste des utilisateurs"),
        "journal": _("Journal d'audit"),
        "historique": _("Historique des statuts"),
    }
    return titles[kind], headers, rows


def _filters_comment(filters: dict) -> str:
    parts = []
    if filters.get("date_from"):
        parts.append(f"du {filters['date_from'].strftime('%d/%m/%Y')}")
    if filters.get("date_to"):
        parts.append(f"au {filters['date_to'].strftime('%d/%m/%Y')}")
    if filters.get("faculty"):
        parts.append(f"faculté : {filters['faculty'].name}")
    if filters.get("department"):
        parts.append(f"département : {filters['department'].name}")
    if filters.get("problem_type"):
        parts.append(f"catégorie : {filters['problem_type'].name}")
    return " · ".join(parts) if parts else _("Toutes les requêtes")


def _record_export(request, kind: str) -> None:
    try:
        audit_service.record(
            request,
            AuditLog.Action.EXPORT,
            model_label="reports.Report",
            object_repr=f"{kind} · {_filters_comment(parse_filters(request))}",
            changes={"kind": kind},
        )
    except Exception:  # noqa: BLE001 — l'export ne doit pas échouer sur l'audit.
        pass


# --------------------------------------------------------------------------- #
# Réponses HTTP
# --------------------------------------------------------------------------- #

def csv_response(request, kind: str, university=None) -> HttpResponse:
    """Export CSV (UTF-8 BOM, séparateur `;`, ouvert dans Excel FR)."""
    filters = parse_filters(request, university)
    title, headers, rows = dataset(kind, filters, university)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)
    response = HttpResponse(
        "\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8"
    )
    filename = f"{kind}-{timezone.localdate().isoformat()}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    _record_export(request, kind)
    return response


def pdf_response(request, kind: str, university=None) -> HttpResponse:
    """Export PDF (reportlab, paysage A4, tableau limité à MAX_PDF_ROWS)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    filters = parse_filters(request, university)
    title, headers, rows = dataset(kind, filters, university)
    truncated = len(rows) > MAX_PDF_ROWS
    rows = rows[:MAX_PDF_ROWS]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=str(title),
    )
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "cell", parent=styles["Normal"], fontSize=7.5, leading=9
    )
    header_style = ParagraphStyle(
        "hcell", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.white, alignment=TA_CENTER,
    )

    def as_paragraph(value, style):
        return Paragraph(str(value).replace("&", "&amp;").replace("<", "&lt;"), style)

    story = [
        Paragraph(str(title), styles["Title"]),
        Paragraph(f"{_('Période / périmètre')} : {_filters_comment(filters)}", styles["Normal"]),
        Spacer(1, 4 * mm),
    ]
    data = [[as_paragraph(h, header_style) for h in headers]]
    for row in rows:
        data.append([as_paragraph(value, cell_style) for value in row])

    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    if truncated:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                f"{_('Aperçu limité à')} {len(rows)} {_('lignes')} — "
                f"{_('export CSV complet disponible.')}",
                styles["Italic"],
            )
        )
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            f"{_('Généré le')} {timezone.localtime().strftime('%d/%m/%Y %H:%M')} — UnivReq",
            styles["Normal"],
        )
    )
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    filename = f"{kind}-{timezone.localdate().isoformat()}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    _record_export(request, kind)
    return response
