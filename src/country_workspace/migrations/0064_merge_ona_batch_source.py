from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0055_add_ona_batch_source"),
        ("country_workspace", "0063_alter_rdp_country_office_and_more"),
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
