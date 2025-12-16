from typing import TYPE_CHECKING, Sequence

from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.db.models import Subquery, OuterRef, QuerySet
from django_celery_boost.admin import CeleryTaskModelAdmin
from django_celery_results.models import TaskResult

from ..models import AsyncJob
from .base import BaseModelAdmin
from .filters import FailedFilter
from .mixins import JobErrorDisplayMixin

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(AsyncJob)
class AsyncJobAdmin(CeleryTaskModelAdmin, BaseModelAdmin, JobErrorDisplayMixin):
    list_display = ("program", "type", "status", "owner")
    autocomplete_fields = ("program", "owner", "batch", "content_type", "rdp")
    list_filter = (
        ("program__country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="program__country_office")),
        ("owner", AutoCompleteFilter),
        "type",
        FailedFilter,
    )

    def get_queryset(self, request: "HttpRequest") -> QuerySet:
        task_result_qs = TaskResult.objects.filter(task_id=OuterRef("curr_async_result_id")).values("status")[:1]
        return (
            super()
            .get_queryset(request)
            .select_related("program__country_office", "owner")
            .annotate(status=Subquery(task_result_qs))
        )

    def status(self, obj: AsyncJob) -> str:
        return obj.status

    def get_readonly_fields(self, request: "HttpRequest", obj: "AsyncJob | None" = None) -> Sequence[str]:
        if obj:
            return "program", "batch", "owner", "local_status", "type", "action", "sentry_id", "formatted_error"
        return super().get_readonly_fields(request, obj)
