"""
Consumer WebSocket — tickets (ARCHITECTURE §10, Prompt 16).

Chaque utilisateur (étudiant ou enseignant) rejoint un groupe dédié
`user_{user_id}` : un enseignant ne reçoit que les événements concernant ses
propres requêtes. Les événements de changement de statut y sont diffusés par
`tickets/signals.py` (uniquement après commit).

Sécurité :
  * connexion refusée aux anonymes (4401) et aux comptes sans profil métier (4403) ;
  * le canal est **lecture seule** : toute tentative de mutation envoyée par le
    client (changement de statut, affectation…) est rejetée — les mutations
    passent exclusivement par les endpoints HTTP sécurisés (CSRF + appartenance).
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer


def _has_business_profile(user):
    """True si l'utilisateur possède un profil étudiant ou enseignant."""
    if getattr(user, "is_superuser", False):
        return True
    # getattr sur OneToOne lève RelatedObjectDoesNotExist (sous-classe
    # d'AttributeError) → hasattr renvoie False sans exception.
    return hasattr(user, "student_profile") or hasattr(user, "teacher_profile")


class TicketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            # Accept puis fermeture avec code : les navigateurs n'exposent pas
            # le code HTTP de la négociation — un refus avant accept serait
            # journalisé comme une simple panne (« connection failed ») sans
            # code, et le client reconecterait indéfiniment.
            await self.accept()
            await self.close(code=4401)
            return

        if not await database_sync_to_async(_has_business_profile)(user):
            await self.accept()
            await self.close(code=4403)
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        """
        Canal lecture seule : le client ne peut jamais muter un statut ou une
        affectation par WebSocket. Toute tentative reçoit une erreur explicite
        et n'aucune écriture n'est effectuée (les mutations exigent les
        endpoints HTTP + CSRF + contrôle d'appartenance).
        """
        await self.send(
            text_data=json.dumps(
                {
                    "type": "error",
                    "code": "mutation_forbidden",
                    "message": "Mutations are not allowed over WebSocket; use the HTTP endpoints.",
                }
            )
        )

    async def ticket_status_changed(self, event):
        """Relaie le payload diffusé vers le navigateur client."""
        await self.send(text_data=json.dumps(event["message"]))
