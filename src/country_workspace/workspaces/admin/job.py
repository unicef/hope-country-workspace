from typing import TYPE_CHECKING, Any

from admin_extra_buttons.decorators import button
from django.contrib.admin import register
from django_celery_boost.admin import CeleryTaskModelAdmin
from django_celery_boost.models import CeleryTaskModel
from strategy_field.utils import fqn

from country_workspace.admin.mixins import JobErrorDisplayMixin
from country_workspace.state import state
from country_workspace.tasks import clean_program_data
from country_workspace.workspaces.models import CountryAsyncJob
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.permissions import can_debug_async_job
from country_workspace.workspaces.sites import workspace

from .filters import ChoiceFilter, UserAutoCompleteFilter, WFailedFilter

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.db.models import QuerySet


@register(CountryAsyncJob, site=workspace)
class CountryJobAdmin(
    CeleryTaskModelAdmin,
    WorkspaceModelAdmin,
    JobErrorDisplayMixin,
):
    queue_template = "workspace/celery_boost/queue.html"

    list_display = (
        "description",
        "status",
        "info",
        "datetime_queued",
        "completed_time",
        # "type",
        "queue_position",
        "owner",
    )
    list_filter = (("type", ChoiceFilter), WFailedFilter, ("owner", UserAutoCompleteFilter))
    search_fields = ("description",)

    def get_fields(self, request: "HttpRequest", obj: "CountryAsyncJob | None" = None) -> tuple[str, ...]:
        fields: list[str] = ["description", "error"]
        if request.user.is_superuser:
            fields.append("result")
        return tuple(fields)

    def get_readonly_fields(self, request: "HttpRequest", obj: "CountryAsyncJob | None" = None) -> tuple[str, ...]:
        readonly_fields: list[str] = ["error"]
        if request.user.is_superuser:
            readonly_fields.append("result")
        return tuple(readonly_fields)

    def get_form(self, request: "HttpRequest", obj: "CountryAsyncJob | None" = None, **kwargs: Any) -> Any:
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["description"].widget.attrs["style"] = "width: 800px;"
        return form

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False

    def has_delete_permission(self, request: "HttpRequest", obj: "CountryAsyncJob|None" = None) -> bool:
        return False

    def has_queue_permission(self, perm: str, request: "HttpRequest", obj: CeleryTaskModel | None) -> bool:
        if not can_debug_async_job(request, obj):
            return False
        if perm != "queue" or not isinstance(obj, CountryAsyncJob) or obj.program_id is None:
            return True
        if obj.action == fqn(clean_program_data):
            return obj.program.cleanup_in_progress
        return not obj.program.cleanup_in_progress

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
        permission=can_debug_async_job,
        html_attrs={"title": "Checks errors in Celery."},
    )
    def celery_check(self, request: "HttpRequest", pk: str) -> "HttpResponse":
        obj = self.get_object(request, pk)
        obj.check()
