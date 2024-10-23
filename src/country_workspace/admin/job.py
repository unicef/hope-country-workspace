from django.contrib import admin

from django_celery_boost.admin import CeleryTaskModelAdmin

from ..models import AsyncJob
from .base import BaseModelAdmin


@admin.register(AsyncJob)
class AsyncJobAdmin(CeleryTaskModelAdmin, BaseModelAdmin):
    list_display = (
        "program",
        "type",
    )
