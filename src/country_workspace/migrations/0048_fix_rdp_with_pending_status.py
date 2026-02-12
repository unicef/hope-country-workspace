from django.db import migrations
from django.db.models import F, Subquery, Window
from django.db.models.functions import RowNumber
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


PENDING_STATUS = "PENDING"
FAILURE_STATUS = "FAILURE"


def failure_pending_rdp(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    rdp = apps.get_model("country_workspace", "RDP")

    extra_pending = (
        rdp.objects.filter(status=PENDING_STATUS)
        .annotate(
            rn=Window(
                expression=RowNumber(),
                partition_by=[F("program_id")],
                order_by=[F("last_modified").desc(), F("pk").desc()],
            )
        )
        .filter(rn__gt=1)
        .values("pk")
    )

    rdp.objects.filter(pk__in=Subquery(extra_pending)).update(status=FAILURE_STATUS)


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0043_batch_status_and_kobo_page"),
    ]

    operations = [
        migrations.RunPython(failure_pending_rdp, migrations.RunPython.noop),
    ]
