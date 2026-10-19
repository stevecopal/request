"""
Droits de décision — « qui peut examiner, valider, refuser, clôturer ».

Base : seul l'enseignant **assigné** au dossier peut décider (boutons Reçu,
Prise en charge, Infos supplémentaires, Accepter, Rejeter, Transférer).
L'administrateur (superuser) ne pilote ni le statut ni l'affectation : il
consulte les requêtes en lecture seule (détail, statut, temps de traitement).
Les `DecisionRule` actives du type de requête **élargissent** ce droit aux
périmètres listés (enseignants du département, membres du service, enseignant
assigné) — jamais aux administrateurs.

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


def _is_assigned_teacher(user, ticket) -> bool:
    """True si `user` est l'enseignant assigné (comparaison via le profil)."""
    if ticket.teacher_id is None:
        return False
    try:
        teacher = getattr(user, "teacher_profile", None)
    except AttributeError:
        teacher = None
    # Profil présent (requêtes `@teacher_required`) → comparaison UUID exacte ;
    # sinon repli sur l'ID utilisateur (ex. tests sans profil résolu).
    if teacher is not None:
        return ticket.teacher_id == teacher.pk
    try:
        teacher_user_id = ticket.teacher.user_id
    except Exception:
        return False
    return teacher_user_id == user.pk


def _matches(rule: DecisionRule, user, ticket) -> bool:
    scope = rule.scope
    if scope == DecisionRule.Scope.ASSIGNED:
        return _is_assigned_teacher(user, ticket)
    if scope == DecisionRule.Scope.ADMIN:
        # L'admin ne décide jamais (lecture seule) : ce périmètre est neutre.
        return False
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

    * enseignant assigné → toujours (boutons du workflow enseignant) ;
    * administrateur (superuser) → jamais : lecture seule (détail, statut,
      temps de traitement), sans pilotage du statut ni de l'affectation ;
    * sinon → une règle active du type couvre l'action (« clôturer » couvre
      aussi valider/refuser, puisqu'il s'agit d'une décision terminale).
      Le périmètre « administrateurs » d'une règle n'ouvre plus aucun droit.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return False
    if _is_assigned_teacher(user, ticket):
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
