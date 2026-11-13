from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0075_biographic_deduplication"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="rdpoperation",
            name="external_id",
        ),
    ]
