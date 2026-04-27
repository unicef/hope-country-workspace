from django.db import transaction
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from packaging.version import Version

from country_workspace.tasks import SYNC_HOPE_DATA_PERIODIC_TASK_NAME

_script_for_version = Version("0.1.0")

TASK_PATH = "country_workspace.tasks.sync_hope_data"
TASK_QUEUE = "queue_hcw"


def forward() -> None:
    with transaction.atomic():
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.HOURS,
        )
        PeriodicTask.objects.update_or_create(
            name=SYNC_HOPE_DATA_PERIODIC_TASK_NAME,
            defaults={
                "task": TASK_PATH,
                "interval": schedule,
                "crontab": None,
                "solar": None,
                "clocked": None,
                "queue": TASK_QUEUE,
                "enabled": True,
                "description": "Synchronize HOPE reference data (programs and geo) every hour.",
            },
        )


def backward() -> None:
    with transaction.atomic():
        PeriodicTask.objects.filter(name=SYNC_HOPE_DATA_PERIODIC_TASK_NAME).delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
