import country_workspace.validators.mapping
import concurrency.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0040_add_originating_id_to_validable"),
    ]

    operations = [
        migrations.CreateModel(
            name="Transformer",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_modified", models.DateTimeField(auto_now=True)),
                ("version", concurrency.fields.IntegerVersionField(default=0, help_text="record revision number")),
                ("name", models.CharField(max_length=255)),
                ("description", models.CharField(blank=True, max_length=255)),
                (
                    "value_transformations",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Value transformation rules (one per line). Format: `fieldname:old_value=new_value`. Example: `sex:M=MALE` or `sex:F=FEMALE`.",
                        validators=[country_workspace.validators.mapping.ValueTransformationRulesValidator()],
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)ss",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "office",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transformers",
                        to="country_workspace.office",
                        help_text="Business Area (Office) this transformer belongs to",
                    ),
                ),
            ],
            options={
                "verbose_name": "Transformer",
                "verbose_name_plural": "Transformers",
                "unique_together": {("office", "name")},
            },
        ),
    ]
