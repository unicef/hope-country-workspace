from typing import TYPE_CHECKING

from admin_extra_buttons.decorators import button
from django.contrib.admin import register
from django_celery_boost.admin import CeleryTaskModelAdmin

from ..models import CountryAsyncJob
from ..options import WorkspaceModelAdmin
from ..sites import workspace
from .filters import ChoiceFilter, UserAutoCompleteFilter, WFailedFilter

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@register(CountryAsyncJob, site=workspace)
class CountryJobAdmin(CeleryTaskModelAdmin, WorkspaceModelAdmin):
    queue_template = "workspace/celery_boost/queue.html"

    list_display = (
        "description",
        "datetime_queued",
        "started",
        "completed_time",
        # "type",
        "queue_position",
        "status",
        "owner",
    )
    list_filter = (("type", ChoiceFilter), WFailedFilter, ("owner", UserAutoCompleteFilter))
    search_fields = ("name",)
    fields = ("description",)

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False

    def has_delete_permission(self, request: "HttpRequest", obj: "CountryAsyncJob|None" = None) -> bool:
        return False

    def status(self, obj: "CountryAsyncJob|None") -> str:
        return obj.task_status

    def completed_time(self, obj: "CountryAsyncJob|None") -> str:
        try:
            return obj.task_info["completed_at"]
        except (KeyError, AttributeError):
            return "Pending"

    @button(
        label="Check",
        permission=lambda r, o, handler: handler.model_admin.has_queue_permission("queue", r, o),
        html_attrs={"title": "Checks errors in Celery."},
    )
    def celery_check(self, request: "HttpRequest", pk: str) -> "HttpResponse":  # type: ignore
        obj = self.get_object(request, pk)
        obj.check()
