from django.template import Library

register = Library()

_HIDDEN_CELERY_INFO = frozenset(
    {
        "traceback",
        "children",
        "task_args",
        "task_kwargs",
    }
)


@register.filter
def is_celery_info_visible(key: str, is_superuser: bool) -> bool:
    if key in _HIDDEN_CELERY_INFO:
        return False
    return not (key == "result" and not is_superuser)
