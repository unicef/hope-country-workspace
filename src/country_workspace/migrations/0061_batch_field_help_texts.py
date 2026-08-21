from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0060_remove_individual_update_update_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="batch",
            name="import_date",
            field=models.DateTimeField(auto_now=True, help_text="Date and time this batch was created."),
        ),
        migrations.AlterField(
            model_name="batch",
            name="imported_by",
            field=models.ForeignKey(
                help_text="User who started the import.",
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="name",
            field=models.CharField(
                blank=True,
                help_text="Name of this import batch.",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="source",
            field=models.CharField(
                blank=True,
                choices=[("RDI", "Rdi file"), ("AURORA", "Aurora"), ("KOBO", "Kobo")],
                help_text="Where the records were imported from (RDI file, Aurora, or Kobo).",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="status",
            field=models.CharField(
                choices=[("LOADING", "Loading"), ("COMPLETE", "Complete")],
                db_index=True,
                default="LOADING",
                help_text=(
                    "Loading while the import is still processing. Complete when the source-specific import "
                    "has finished. Validation may continue afterwards."
                ),
                max_length=32,
            ),
        ),
    ]
