from django.core.management import call_command
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def migrate_flex_files(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # runs the management command so it can also be resumed out of band
    call_command("migrate_flex_files")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("country_workspace", "0064_flexfieldfile"),
    ]

    operations = [
        migrations.RunPython(migrate_flex_files, migrations.RunPython.noop),
    ]
