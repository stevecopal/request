"""
Centre de notifications — accounts (fragments + actions AJAX).

Les notifications sont créées par `tickets/signals.py` après commit :
chaque événement de workflow notifie la partie concernée (jamais l'acteur).

Sécurité : toutes les vues sont strictement bornées à `request.user` —
aucun identifiant utilisateur n'est lu dans la requête.
"""

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from accounts.decorators import login_required_json
from accounts.models import Notification
from accounts.spa import spa_page
from accounts.utils import role_name


@spa_page
@login_required_json
def notifications_fragment(request):
    """Fragment « Notifications » injecté dans #spa-viewport."""
    notifications = (
        Notification.objects.filter(user=request.user)
        .select_related("ticket")
        .order_by("-created_at")[:50]
    )
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return render(
        request,
        "partials/notifications.html",
        {
            "notifications": notifications,
            "unread_count": unread,
            "role": role_name(request.user),
        },
    )


@require_POST
@login_required_json
def notifications_read(request):
    """
    Marque des notifications comme lues.

    Sans paramètre : toutes les notifications non lues de l'utilisateur.
    Avec `ids` (CSV d'UUID) : uniquement celles listées — toutes contrôlées
    par le queryset `user=request.user` (impossible de marquer le bien d'autrui).
    """
    queryset = Notification.objects.filter(user=request.user, is_read=False)

    ids = (request.POST.get("ids") or "").strip()
    if ids:
        id_list = [value.strip() for value in ids.split(",") if value.strip()]
        queryset = queryset.filter(pk__in=id_list)

    updated = queryset.update(is_read=True)
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse(
        {
            "status": "success",
            "message": str(_("Notifications marquées comme lues.")),
            "updated": updated,
            "unread_notifications": unread,
        }
    )
