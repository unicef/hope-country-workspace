from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def flatten_rdp_selection(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Copy parent beneficiary links into child RDPs before dropping parent."""
    Rdp = apps.get_model("country_workspace", "Rdp")

    for rdp in Rdp.objects.exclude(parent_id__isnull=True).iterator():
        parent = rdp.parent
        has_households = parent.households.exists()
        has_individuals = parent.individuals.exists()

        if has_households and has_individuals:
            raise RuntimeError(f"RDP #{parent.pk} has both household and individual selections.")

        if has_households:
            rdp.households.set(parent.households.all())
        elif has_individuals:
            rdp.individuals.set(parent.individuals.all())


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0054_rdp_deduplication_snapshots_and_more"),
    ]

    operations = [
        migrations.RunPython(flatten_rdp_selection, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="rdp",
            name="parent",
        ),
    ]
