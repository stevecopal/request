"""
Droits de décision (C4) — « qui peut examiner, valider, refuser, clôturer ».

Base (inchangée) : l'enseignant **assigné** au dossier et les administrateurs
peuvent toujours décider. Les `DecisionRule` actives du type de requête
**élargissent** ce droit aux périmètres listés (enseignants du département,
membres du service, administrateurs, enseignant assigné).

Appelé par l'endpoint de décision (`tickets.views.status_processor`) avant
toute transition — un refus vaut 403, sans effet de bord.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from core_scolarite.models import DecisionRule, ServiceAssignment
from tickets.models import Ticket

__all__ = ["action_for_status", "may_decide", "DecisionDenied"]

# Statut cible → action de décision configurée en console (C4).
_ACTION_BY_TARGET = {
    Ticket.Status.RESOLVED: DecisionRule.Action.VALIDATE,
    Ticket.Status.REJECTED: DecisionRule.Action.REJECT,
}


class DecisionDenied(Exception):
    """Aucun droit de décision sur ce dossier pour cet utilisateur."""

    def __init__(self, message=None):
        self.message = str(
            message
            or _(
                "Vous n'avez pas le droit de prendre cette décision sur ce dossier. "
                "Contactez un administrateur si une règle de workflow est à réviser."
            )
        )
        super().__init__(self.message)


def action_for_status(new_status: str) -> str:
    """Action configurée pour une transition cible donnée."""
    return _ACTION_BY_TARGET.get(new_status, DecisionRule.Action.EXAMINE)


def _matches(rule: DecisionRule, user, ticket) -> bool:
    scope = rule.scope
    if scope == DecisionRule.Scope.ASSIGNED:
        return ticket.teacher_id is not None and user.pk == ticket.teacher_id
    if scope == DecisionRule.Scope.ADMIN:
        return bool(user.is_superuser)
    if scope == DecisionRule.Scope.SERVICE:
        # Membres du service responsable du type OU du service destinataire
        # après transmission B6 (ticket.assigned_service).
        service_ids = set()
        if ticket.problem_type.service_id:
            service_ids.add(ticket.problem_type.service_id)
        if ticket.assigned_service_id:
            service_ids.add(ticket.assigned_service_id)
        if not service_ids:
            return False
        return ServiceAssignment.objects.filter(
            service_id__in=service_ids, user=user, is_active=True
        ).exists()
    if scope == DecisionRule.Scope.DEPARTMENT:
        teacher = getattr(user, "teacher_profile", None)
        if teacher is None:
            return False
        department_id = (
            ticket.course.department_id if ticket.course_id else ticket.student.department_id
        )
        return department_id is not None and teacher.department_id == department_id
    return False


def may_decide(user, ticket, action: str | None = None, new_status: str | None = None) -> bool:
    """
    True si `user` peut prendre la décision sur `ticket`.

    * administrateur (superuser) → toujours ;
    * enseignant assigné → toujours (base inchangée) ;
    * sinon → une règle active du type couvre l'action (« clôturer » couvre
      aussi valider/refuser, puisqu'il s'agit d'une décision terminale).
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if ticket.teacher_id is not None and user.pk == ticket.teacher_id:
        return True

    if action is None:
        action = action_for_status(new_status) if new_status else DecisionRule.Action.EXAMINE

    actions = {action}
    if action in (DecisionRule.Action.VALIDATE, DecisionRule.Action.REJECT):
        actions.add(DecisionRule.Action.CLOSE)

    rules = DecisionRule.objects.filter(
        problem_type_id=ticket.problem_type_id,
        is_active=True,
        action__in=list(actions),
    ).order_by("position", "id")
    return any(_matches(rule, user, ticket) for rule in rules)
