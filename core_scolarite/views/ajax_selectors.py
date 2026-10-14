"""
Sélecteurs AJAX — core_scolarite (ARCHITECTURE §8.3, Prompt 9).

`form_config` alimente le formulaire dynamique : à partir d'un `problem_type_id`,
il renvoie les UE du **département de l'étudiant connecté** (jamais un ID fourni),
les enseignants de ce département et les règles de pièces jointes à injecter.

Optimisations : `.values()` uniquement (pas d'instances complètes), requêtes
indexées (department) → exécution visée < 10 ms.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from accounts.decorators import student_required
from accounts.models import Teacher
from core_scolarite.models import ConditionalRule, Course, Enrollment, ProblemType


def _teacher_label(title_label, first_name, last_name, username):
    name = f"{first_name} {last_name}".strip() or username
    return f"{title_label} {name}".strip()


@require_GET
@student_required
def form_config(request):
    """Configuration complète du formulaire pour un type de problème donné."""
    problem_type_id = request.GET.get("problem_type_id")
    if not problem_type_id:
        return JsonResponse(
            {"status": "error", "message": "problem_type_id requis."}, status=400
        )

    problem_type = ProblemType.visible_to(student_university := request.student.university).filter(
        pk=problem_type_id
    ).only(
        "id", "name", "requires_course", "description", "university", "is_active", "position"
    ).first()
    if problem_type is None:
        return JsonResponse(
            {"status": "error", "message": "Type de problème introuvable."}, status=404
        )

    student = request.student
    if not student.is_onboarded:
        return JsonResponse(
            {
                "status": "error",
                "message": "Complétez d'abord votre profil (faculté et département).",
                "code": "onboarding_required",
            },
            status=400,
        )

    courses = []
    enrollment_filtered = False
    if problem_type.requires_course:
        # Filtre par inscriptions réelles quand elles existent, sinon repli
        # sur le département de l'étudiant (mode MVP).
        if Enrollment.objects.filter(student=student).exists():
            enrollment_filtered = True
            courses = list(
                Course.objects.filter(enrollments__student=student)
                .values("id", "code", "name")
                .order_by("code")
            )
        else:
            courses = list(
                Course.objects.filter(department_id=student.department_id)
                .values("id", "code", "name")
                .order_by("code")
            )

    title_labels = dict(Teacher.TITLE_CHOICES)
    teachers = [
        {
            "id": row["id"],
            "label": _teacher_label(
                str(title_labels.get(row["title"], row["title"])),
                row["user__first_name"],
                row["user__last_name"],
                row["user__username"],
            ),
        }
        for row in Teacher.objects.filter(department_id=student.department_id)
        .values("id", "title", "user__first_name", "user__last_name", "user__username")
        .order_by("user__last_name")
    ]

    attachments = list(
        problem_type.required_attachments.values(
            "id", "label", "is_required", "allowed_types", "max_size_mb"
        )
    )

    # Champs dynamiques + règles conditionnelles (rendus côté client,
    # réévalués côté serveur à la soumission).
    fields = list(
        problem_type.fields.filter(is_active=True)
        .order_by("position", "id")
        .values("key", "label", "field_type", "is_required", "help_text", "choices_list")
    )
    for field in fields:
        field["choices"] = [
            line.strip()
            for line in (field.pop("choices_list") or "").splitlines()
            if line.strip()
        ]
    rules = list(
        ConditionalRule.objects.filter(field__problem_type=problem_type)
        .order_by("field__position", "id")
        .values("field__key", "depends_on__key", "operator", "value", "action")
    )
    for rule in rules:
        rule["field"] = rule.pop("field__key")
        rule["depends_on"] = rule.pop("depends_on__key")

    return JsonResponse(
        {
            "status": "success",
            "requires_course": problem_type.requires_course,
            "enrollment_filtered": enrollment_filtered,
            "problem_type": {
                "id": problem_type.id,
                "name": problem_type.name,
                "description": problem_type.description,
            },
            "courses": courses,
            "teachers": teachers,
            "attachments": attachments,
            "fields": fields,
            "rules": rules,
        }
    )


@require_GET
@student_required
def problem_types(request):
    """Liste des types de requête **actifs et visibles** pour l'université de l'étudiant."""
    data = list(
        ProblemType.visible_to(request.student.university)
        .values("id", "name", "requires_course")
        .order_by("position", "name")
    )
    return JsonResponse({"status": "success", "problem_types": data})
