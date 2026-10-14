"""
Modèles de base partagés du projet (non enregistrés comme app Django).

`UUIDModel` fournit une clé primaire UUID v4 à tous les modèles métier.
Décision projet : identifiants UUID partout (non devinables, sûrs dans les
URLs et les payloads AJAX, pas d'énumération d'objets). Les modèles abstraits
s'importent librement depuis n'importe quelle app.
"""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """Base abstraite : clé primaire UUID v4 non éditable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True

    @property
    def short_id(self) -> str:
        """Représentation courte (8 premiers caractères) pour l'affichage/UI."""
        return str(self.id)[:8]
