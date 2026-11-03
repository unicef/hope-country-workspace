from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


ACTION_REPLACEMENTS = (
    (
        "country_workspace.rdp.lifecycle.create_rdp_core",
        "country_workspace.rdp.lifecycle.creation.create_rdp_core",
    ),
    (
        "country_workspace.rdp.lifecycle.cancel_existing_rdp_core",
        "country_workspace.rdp.lifecycle.cancellation.cancel_existing_rdp_core",
    ),
    (
        "country_workspace.rdp.lifecycle.reject_cancelled_rdp_set_core",
        "country_workspace.rdp.deduplication.workflow.reject_cancelled_rdp_set_core",
    ),
)


def _replace_action(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
    *,
    old: str,
    new: str,
) -> None:
    """Replace a persisted AsyncJob action path."""
    AsyncJob = apps.get_model("country_workspace", "AsyncJob")
    AsyncJob.objects.using(schema_editor.connection.alias).filter(action=old).update(action=new)


def forward(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Update persisted RDP lifecycle job action paths."""
    for old, new in ACTION_REPLACEMENTS:
        _replace_action(apps, schema_editor, old=old, new=new)


def backward(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore previous RDP lifecycle job action paths."""
    for old, new in ACTION_REPLACEMENTS:
        _replace_action(apps, schema_editor, old=new, new=old)


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0072_alter_rdpoperation_id_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
