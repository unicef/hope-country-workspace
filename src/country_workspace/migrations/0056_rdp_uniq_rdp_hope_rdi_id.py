from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def validate_unique_hope_rdi_id(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Rdp = apps.get_model("country_workspace", "Rdp")
    db_alias = schema_editor.connection.alias

    duplicates = list(
        Rdp.objects.using(db_alias)
        .filter(hope_rdi_id__isnull=False)
        .values("hope_rdi_id")
        .annotate(count=models.Count("pk"))
        .filter(count__gt=1)
        .order_by("hope_rdi_id")
    )
    if duplicates:
        details = ", ".join(f"{item['hope_rdi_id']} ({item['count']})" for item in duplicates[:10])
        raise RuntimeError(f"Cannot add unique RDP hope_rdi_id constraint. Duplicates found: {details}")


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0055_alter_rdp_status"),
    ]

    operations = [
        migrations.RunPython(validate_unique_hope_rdi_id, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="rdp",
            constraint=models.UniqueConstraint(
                condition=models.Q(("hope_rdi_id__isnull", False)),
                fields=("hope_rdi_id",),
                name="uniq_rdp_hope_rdi_id",
                violation_error_message="There is already an RDP for this HOPE RDI.",
            ),
        ),
    ]
