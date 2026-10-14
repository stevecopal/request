"""
Routage WebSocket (ARCHITECTURE §5.5).

`tickets.consumers.TicketConsumer` sur ws://<host>/ws/tickets/
Groupes : user_{user_id} (étudiants et enseignants).
"""

from django.urls import path

from tickets.consumers import TicketConsumer

websocket_urlpatterns = [
    path("ws/tickets/", TicketConsumer.as_asgi()),
]
