from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0066_remove_legacy_rdp_deduplication"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batch",
            name="source",
            field=models.CharField(
                blank=True,
                choices=[("RDI", "Rdi file"), ("AURORA", "Aurora"), ("KOBO", "Kobo"), ("ONA", "ONA / INFORM")],
                help_text="Where the records were imported from (RDI file, Aurora, or Kobo).",
                max_length=255,
                null=True,
            ),
        ),
    ]
