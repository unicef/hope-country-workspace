import os
from typing import Any

import sentry_sdk
from celery import Celery, signals

from hope_country_workspace.config import settings

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "hope_country_workspace.config.settings"
)


app = Celery("hde")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS, related_name="celery_tasks")


@signals.celeryd_init.connect
def init_sentry(**_kwargs: Any) -> None:
    sentry_sdk.set_tag("celery", True)
