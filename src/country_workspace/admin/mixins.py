import json
from typing import Any

from django.utils.html import format_html
from django_celery_results.models import TaskResult


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

            if isinstance(data, (dict, list)):
                return format_html("<pre>{}</pre>", json.dumps(data, indent=2))
        except (json.JSONDecodeError, TypeError):
            pass

        return str(task_result.result)
