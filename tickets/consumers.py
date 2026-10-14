"""
Consumer WebSocket — tickets (ARCHITECTURE §10, Prompt 16).

Chaque utilisateur (étudiant ou enseignant) rejoint un groupe dédié
`user_{user_id}`. Les événements de changement de statut y sont diffusés par
`tickets/signals.py`. Un utilisateur anonyme est refusé (code 4401).
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class TicketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def ticket_status_changed(self, event):
        """Relaie le payload diffusé vers le navigateur client."""
        await self.send(text_data=json.dumps(event["message"]))
