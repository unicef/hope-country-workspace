from typing import TYPE_CHECKING
import json
from admin_extra_buttons.decorators import button
from django.contrib.admin import register
from django.utils.html import format_html
from django_celery_boost.admin import CeleryTaskModelAdmin
from django_celery_boost.models import CeleryTaskModel
from django_celery_results.models import TaskResult

from ..permissions import can_debug_async_job
from ..models import CountryAsyncJob
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter, UserAutoCompleteFilter, WFailedFilter
from ...state import state

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.db.models import QuerySet


@register(CountryAsyncJob, site=workspace)
class CountryJobAdmin(CeleryTaskModelAdmin, WorkspaceModelAdmin):
    queue_template = "workspace/celery_boost/queue.html"

    list_display = (
        "description",
        "info",
        "datetime_queued",
        "completed_time",
        # "type",
        "queue_position",
        "status",
        "owner",
    )
    list_filter = (("type", ChoiceFilter), WFailedFilter, ("owner", UserAutoCompleteFilter))
    search_fields = ("description",)
    fields = ("description", "formatted_error")
    readonly_fields = ("formatted_error",)

    def formatted_error(self, obj: "CountryAsyncJob | None") -> str:
        if not obj or not obj.curr_async_result_id:
            return ""

        task_result = TaskResult.objects.filter(task_id=obj.curr_async_result_id).first()
        if not task_result or not task_result.result:
            return ""

        try:
            if isinstance(task_result.result, str):
                data = json.loads(task_result.result)
            else:
                data = task_result.result
        except (json.JSONDecodeError, TypeError):
            data = task_result.result

        return format_html("<pre>{}</pre>", json.dumps(data, indent=2))

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False

    def has_delete_permission(self, request: "HttpRequest", obj: "CountryAsyncJob|None" = None) -> bool:
        return False

    def has_queue_permission(self, perm: str, request: "HttpRequest", obj: CeleryTaskModel | None) -> bool:
        return can_debug_async_job(request, obj)

    def status(self, obj: "CountryAsyncJob|None") -> str:
        return obj.task_status

    def completed_time(self, obj: "CountryAsyncJob|None") -> str:
        try:
            return obj.task_info["completed_at"]
        except (KeyError, AttributeError):
            return "Pending"

    def get_queryset(self, request: "HttpRequest") -> "QuerySet[CountryAsyncJob]":
        return super().get_queryset(request).filter(program=state.program)

    @button(
        label="Check",
        permission=lambda r, o, handler: handler.model_admin.has_queue_permission("queue", r, o),
        html_attrs={"title": "Checks errors in Celery."},
    )
    def celery_check(self, request: "HttpRequest", pk: str) -> "HttpResponse":
        obj = self.get_object(request, pk)
        obj.check()
