"""
Configuration ASGI : HTTP + WebSocket (Django Channels).

Architecture (ARCHITECTURE §5.4) :
  - http   → Django classique (vues, fragments AJAX, admin)
  - websocket → AuthMiddlewareStack (session → scope["user"]) → core.routing
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

django_asgi_app = get_asgi_application()

# Import différé APRÈS get_asgi_application() pour charger les modèles des apps.
from core.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
