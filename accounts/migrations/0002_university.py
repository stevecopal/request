"""
Migration multi-universités — accounts.

1. Crée le modèle University.
2. Ajoute `Faculty.university` nullable, backfill vers une université par
   défaut si nécessaire (préserve les données existantes).
3. Rend le champ non-null, remplace l'unicité globale de `Faculty.name`
   par l'unicité (university, name).

Sûre : toutes les opérations destructrices ne s'exécutent qu'après le
backfill ; réversible en théorie (pas d'op irreversible).
"""

from django.db import migrations, models
import django.db.models.deletion
import uuid


def create_default_university(apps, schema_editor):
    """Crée l'université par défaut si aucune n'existe, puis backfill Faculty."""
    University = apps.get_model("accounts", "University")
    Faculty = apps.get_model("accounts", "Faculty")

    university = University.objects.order_by("name").first()
    if university is None:
        university = University.objects.create(name="Université Nationale")
    Faculty.objects.filter(university__isnull=True).update(university=university)


def unbind_default_university(apps, schema_editor):
    """Aucun nettoyage nécessaire : le backfill ne supprime rien."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="University",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=150, unique=True)),
            ],
            options={
                "verbose_name": "university",
                "verbose_name_plural": "universities",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="faculty",
            name="university",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="faculties",
                to="accounts.university",
            ),
        ),
        migrations.RunPython(create_default_university, unbind_default_university),
        migrations.AlterField(
            model_name="faculty",
            name="university",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="faculties",
                to="accounts.university",
            ),
        ),
        migrations.AlterField(
            model_name="faculty",
            name="name",
            field=models.CharField(max_length=150),
        ),
        migrations.AddConstraint(
            model_name="faculty",
            constraint=models.UniqueConstraint(
                fields=("university", "name"), name="faculty_university_name_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="faculty",
            index=models.Index(
                fields=["university", "name"], name="fac_uni_name_idx"
            ),
        ),
    ]
