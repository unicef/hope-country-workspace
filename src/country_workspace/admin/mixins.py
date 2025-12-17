import json
from typing import Any

from django.utils.html import format_html
from django_celery_results.models import TaskResult


class JobErrorDisplayMixin:
    def formatted_error(self, obj: Any) -> str:
        if not obj or not getattr(obj, "curr_async_result_id", None):
            return ""

        task_result = TaskResult.objects.filter(task_id=obj.curr_async_result_id).first()
        if not task_result or not task_result.result:
            return ""

        try:
            data = json.loads(task_result.result)
        except (json.JSONDecodeError, TypeError):
            data = task_result.result

        return format_html("<pre>{}</pre>", json.dumps(data, indent=2))
