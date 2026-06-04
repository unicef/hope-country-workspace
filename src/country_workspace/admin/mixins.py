import json
from typing import Any

from django.utils.html import format_html
from django_celery_results.models import TaskResult


class JobErrorDisplayMixin:
    def _get_task_result_data(self, obj: Any) -> Any | None:
        if not obj or not getattr(obj, "curr_async_result_id", None):
            return None

        task_result = TaskResult.objects.filter(task_id=obj.curr_async_result_id).first()
        if not task_result or not task_result.result:
            return None

        try:
            if isinstance(task_result.result, str):
                return json.loads(task_result.result)
        except (json.JSONDecodeError, TypeError):
            return task_result.result
        return task_result.result

    @staticmethod
    def _format_application_errors(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        errors = data.get("errors")
        if not errors:
            return ""
        if isinstance(errors, list):
            lines = [str(item) for item in errors if item]
            return "\n".join(lines)
        return str(errors)

    def error(self, obj: Any) -> str:
        if not obj:
            return ""

        task_error = obj.task_info.get("error", "")
        if task_error:
            return task_error

        app_errors = self._format_application_errors(self._get_task_result_data(obj))
        if not app_errors:
            return ""
        return format_html("<pre>{}</pre>", app_errors)

    error.short_description = "Error"

    def result(self, obj: Any) -> str:
        data = self._get_task_result_data(obj)
        if data is None:
            return ""

        if isinstance(data, (dict | list)):
            return format_html("<pre>{}</pre>", json.dumps(data, indent=2))

        return format_html("<pre>{}</pre>", data)
