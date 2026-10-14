"""
Service de création de ticket — tickets (ARCHITECTURE §8.2, Prompt 11).

`create_student_ticket()` :
  1. résout le ProblemType ;
  2. si `requires_course` → l'UE est obligatoire et doit appartenir au
     département de l'étudiant ; l'enseignant cible est le `primary_instructor` ;
     sinon l'enseignant est fourni (déjà filtré par département côté endpoint) ;
  3. vérifie que toutes les pièces **obligatoires** sont présentes ;
  4. valide extension + taille de chaque fichier ;
  5. crée Ticket + TicketAttachment dans un `transaction.atomic()` ; en cas
     d'échec, les fichiers déjà écrits sur disque sont supprimés (pas d'orphelins).
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from accounts.models import AcademicYear, Teacher
from core_scolarite.models import (
    AttachmentConfig,
    Course,
    CourseAssignment,
    Enrollment,
    ProblemType,
)
from core_scolarite.services.form_config import (
    ConfigurationError,
    build_snapshot,
    validate_dynamic_fields,
)
from tickets.models import Ticket, TicketAttachment, TicketStatusHistory


class TicketCreationError(Exception):
    """Erreur métier bloquante lors de la création d'un ticket."""

    def __init__(self, message, field_errors: dict | None = None):
        self.message = str(message)
        self.field_errors = field_errors or {}
        super().__init__(self.message)


def _validate_file(uploaded_file, label):
    """Whitelist d'extension + taille maximale (§9.4)."""
    name = (getattr(uploaded_file, "name", "") or "").lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    if extension not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise TicketCreationError(
            _("Format non autorisé pour « %(label)s » (autorisés : %(exts)s).")
            % {
                "label": label,
                "exts": ", ".join(settings.ALLOWED_UPLOAD_EXTENSIONS),
            }
        )
    if uploaded_file.size > settings.MAX_UPLOAD_SIZE:
        max_mb = settings.MAX_UPLOAD_SIZE // (1024 * 1024)
        raise TicketCreationError(
            _("Le fichier « %(label)s » dépasse la taille maximale de %(max)s Mo.")
            % {"label": label, "max": max_mb}
        )


def _resolve_teacher(student_profile, problem_type, course, teacher_id, academic_year=""):
    if problem_type.requires_course:
        if course is None:
            raise TicketCreationError(
                _("Veuillez sélectionner une unité d'enseignement."),
                {"course": _("Champ obligatoire.")},
            )
        # Filtrage par inscriptions réelles quand elles existent, sinon département.
        has_enrollments = Enrollment.objects.filter(student=student_profile).exists()
        if has_enrollments:
            enrolled = Enrollment.objects.filter(
                student=student_profile, course=course
            ).exists()
            if not enrolled:
                raise TicketCreationError(
                    _("Vous n'êtes pas inscrit à cette unité d'enseignement.")
                )
        elif course.department_id != student_profile.department_id:
            raise TicketCreationError(
                _("L'unité d'enseignement sélectionnée n'appartient pas à votre département.")
            )
        # Responsable automatique : affectation enseignant → cours active pour
        # l'année académique (puis repli sur le primary_instructor historique).
        year_object = None
        if academic_year:
            year_object = AcademicYear.objects.filter(code=academic_year).first()
        teacher = CourseAssignment.responsible(course, year_object)
        if teacher is None:
            teacher = course.primary_instructor
        if teacher is None:
            raise TicketCreationError(
                _("Aucun enseignant n'est assigné à cette unité d'enseignement.")
            )
        # Garde-fou : l'enseignant assigné doit appartenir au même département.
        if (
            student_profile.department_id
            and teacher.department_id != student_profile.department_id
        ):
            raise TicketCreationError(
                _("L'enseignant assigné à cette unité n'appartient pas à votre département.")
            )
        return teacher

    if not teacher_id:
        raise TicketCreationError(
            _("Veuillez sélectionner un enseignant."),
            {"teacher": _("Champ obligatoire.")},
        )
    teacher = Teacher.objects.filter(
        pk=teacher_id, department_id=student_profile.department_id
    ).first()
    if teacher is None:
        raise TicketCreationError(
            _("Enseignant invalide pour votre département.")
        )
    return teacher


@transaction.atomic
def create_student_ticket(
    student_profile,
    problem_type_id,
    description,
    uploaded_files_dict,
    course_id=None,
    teacher_id=None,
    academic_year="",
    form_data=None,
) -> Ticket:
    """
    Crée un ticket pour l'étudiant fourni.

    :param student_profile: profil étudiant (issu de request.user, jamais du client).
    :param problem_type_id: id du type de problème.
    :param description: commentaires de l'étudiant.
    :param uploaded_files_dict: {str(attachment_config_id): UploadedFile}.
    :param course_id: id de l'UE (si le problème l'exige).
    :param teacher_id: id de l'enseignant (si le problème n'exige pas d'UE).
    :param academic_year: session académique déclarée (ex. 2025-2026).
    :param form_data: réponses aux champs dynamiques (validées côté serveur).
    :return: le Ticket créé.
    :raises TicketCreationError: validation échouée (aucune écriture persistée).
    """
    description = (description or "").strip()
    if not description:
        raise TicketCreationError(
            _("La description est obligatoire."), {"description": _("Champ obligatoire.")}
        )

    problem_type = ProblemType.objects.filter(pk=problem_type_id).first()
    if problem_type is None:
        raise TicketCreationError(_("Type de problème introuvable."))
    # Activation + isolation universitaire : un type désactivé ou rattaché à une
    # autre université n'est jamais soumissible (contrôle serveur).
    if not problem_type.is_active:
        raise TicketCreationError(_("Ce type de requête n'est plus disponible."))
    student_university = student_profile.university
    if (
        problem_type.university_id
        and student_university is not None
        and problem_type.university_id != student_university.pk
    ):
        raise TicketCreationError(
            _("Ce type de requête n'est pas disponible dans votre université.")
        )

    # Réponses aux champs dynamiques : obligatoires + règles conditionnelles.
    try:
        answers = validate_dynamic_fields(problem_type, form_data)
    except ConfigurationError as exc:
        raise TicketCreationError(
            _("Certains champs du formulaire sont invalides : %(details)s.")
            % {"details": " ".join(exc.errors)},
            {"form": " ".join(exc.errors)},
        )

    course = None
    if course_id:
        course = Course.objects.filter(pk=course_id).first()

    teacher = _resolve_teacher(
        student_profile, problem_type, course, teacher_id, academic_year
    )

    configs = list(
        AttachmentConfig.objects.filter(problem_type=problem_type).order_by("label")
    )

    # Contrôle des pièces obligatoires.
    missing = [
        config.label
        for config in configs
        if config.is_required and not uploaded_files_dict.get(str(config.id))
    ]
    if missing:
        raise TicketCreationError(
            _("Pièces jointes obligatoires manquantes : %(list)s.")
            % {"list": ", ".join(missing)},
            {"attachments": _("Ajoutez les fichiers requis.")},
        )

    # Validation des fichiers fournis.
    for config in configs:
        uploaded = uploaded_files_dict.get(str(config.id))
        if uploaded is not None:
            _validate_file(uploaded, config.label)

    ticket = Ticket(
        student=student_profile,
        teacher=teacher,
        course=course,
        problem_type=problem_type,
        description=description,
        academic_year=(academic_year or "").strip()[:9],
        status=Ticket.Status.SENT,
        # Figer la configuration utilisée : les modifications ultérieures du
        # type ne déforment jamais l'historique de cette requête.
        config_snapshot=build_snapshot(problem_type),
        form_data=answers,
    )
    # L'étudiant est l'acteur : il ne reçoit pas de notification pour sa propre
    # soumission (posé avant save pour le signal post_save).
    ticket._actor_user_id = student_profile.user_id
    ticket.save()

    written_files = []
    try:
        for config in configs:
            uploaded = uploaded_files_dict.get(str(config.id))
            if uploaded is None:
                continue
            attachment = TicketAttachment.objects.create(
                ticket=ticket, config=config, file=uploaded
            )
            written_files.append(attachment.file.name)
    except Exception:
        # Rollback DB (transaction) + suppression des fichiers déjà écrits.
        for name in written_files:
            ticket.attachments.model._meta.get_field("file").storage.delete(name)
        raise

    # Historique horodaté de la création (dans la même transaction atomique).
    TicketStatusHistory.objects.create(
        ticket=ticket,
        from_status=None,
        to_status=Ticket.Status.SENT,
        actor=student_profile.user,
        actor_role=TicketStatusHistory.ActorRole.STUDENT,
        note=_("Requête soumise."),
    )

    return ticket
