from typing import TYPE_CHECKING, Sequence
from strategy_field.utils import fqn

from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.db.models import Subquery, OuterRef, QuerySet
from django_celery_boost.admin import CeleryTaskModelAdmin
from django_celery_results.models import TaskResult

from country_workspace.models import AsyncJob
from country_workspace.tasks import clean_program_data
from .base import BaseModelAdmin
from .filters import FailedFilter
from .mixins import JobErrorDisplayMixin

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django_celery_boost.models import CeleryTaskModel


@admin.register(AsyncJob)
class AsyncJobAdmin(
    CeleryTaskModelAdmin,
    BaseModelAdmin,
    JobErrorDisplayMixin,
):
    list_display = ("program", "type", "status", "owner")
    autocomplete_fields = ("program", "owner", "batch", "content_type", "rdp")
    list_filter = (
        ("program__country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="program__country_office")),
        ("owner", AutoCompleteFilter),
        "type",
        FailedFilter,
    )

    def has_queue_permission(self, perm: str, request: "HttpRequest", obj: "CeleryTaskModel | None") -> bool:
        if not super().has_queue_permission(perm, request, obj):
            return False
        if perm == "queue" and isinstance(obj, AsyncJob) and obj.program_id is not None:
            return obj.action == fqn(clean_program_data) or not obj.program.cleanup_in_progress
        return True

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
            fields = ["program", "batch", "owner", "local_status", "type", "action", "sentry_id", "error"]
            if request.user.is_superuser:
                fields.append("result")
            return tuple(fields)
        return super().get_readonly_fields(request, obj)
