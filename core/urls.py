"""
Routage racine de l'application (ARCHITECTURE §5.6).

Une application = un namespace ; aucune vue métier n'est montée ici.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("scolarite/", include("core_scolarite.urls")),
    path("tickets/", include("tickets.urls")),
]

# Servir les médias en développement uniquement (production : reverse-proxy,
# contrôle d'accès assuré par la vue de téléchargement — ARCHITECTURE §9.4).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
