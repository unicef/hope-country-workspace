import json
from typing import TYPE_CHECKING, Any

from admin_extra_buttons.decorators import button
from django.utils.html import format_html
from django_celery_results.models import TaskResult
from country_workspace.config.celery import app

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class JobErrorDisplayMixin:
    def result(self, obj: Any) -> str:
        if not obj or not getattr(obj, "curr_async_result_id", None):
            return ""

        task_result = TaskResult.objects.filter(task_id=obj.curr_async_result_id).first()
        if not task_result or not task_result.result:
            return ""

        try:
            if isinstance(task_result.result, str):
                data = json.loads(task_result.result)
            else:
                data = task_result.result

            if isinstance(data, (dict | list)):
                return format_html("<pre>{}</pre>", json.dumps(data, indent=2))
        except (json.JSONDecodeError, TypeError):
            pass

        return str(task_result.result)


class JobCancellationMixin:
    @button(
        label="Stop",
        permission=lambda r, o, handler: handler.model_admin.has_queue_permission("queue", r, o),
        html_attrs={"title": "Request graceful task cancellation."},
    )
    def celery_stop(self, request: "HttpRequest", pk: str) -> "HttpResponse":
        obj = self.get_object(request, pk)
        obj.request_cancellation()
        if obj.curr_async_result_id:
            app.control.revoke(obj.curr_async_result_id, terminate=False)
