import os
from typing import Any

import sentry_sdk
from celery import Celery, signals

from country_workspace.config import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "country_workspace.config.settings")


app = Celery("cw")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS, related_name="tasks")


@signals.celeryd_init.connect
def init_sentry(**_kwargs: Any) -> None:
    sentry_sdk.set_tag("celery", True)
