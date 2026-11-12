from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0074_update_rdp_job_action_paths"),
    ]

    operations = [
        migrations.AlterField(
            model_name="program",
            name="start_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
