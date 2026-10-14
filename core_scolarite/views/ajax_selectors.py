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
from core_scolarite.models import Course, ProblemType


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

    problem_type = (
        ProblemType.objects.filter(pk=problem_type_id)
        .only("id", "name", "requires_course", "description")
        .first()
    )
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
    if problem_type.requires_course:
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
        problem_type.required_attachments.values("id", "label", "is_required")
    )

    return JsonResponse(
        {
            "status": "success",
            "requires_course": problem_type.requires_course,
            "problem_type": {
                "id": problem_type.id,
                "name": problem_type.name,
                "description": problem_type.description,
            },
            "courses": courses,
            "teachers": teachers,
            "attachments": attachments,
        }
    )


@require_GET
@student_required
def problem_types(request):
    """Liste des types de problème disponibles (remplissage du menu déroulant)."""
    data = list(
        ProblemType.objects.values("id", "name", "requires_course").order_by("name")
    )
    return JsonResponse({"status": "success", "problem_types": data})
