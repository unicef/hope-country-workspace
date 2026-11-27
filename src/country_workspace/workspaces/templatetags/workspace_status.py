from typing import Any

from django.template import Library
from django.utils.html import format_html
from django.utils.safestring import SafeString

register = Library()

STATUS_TONES = {
    "ACTIVE": "success",
    "COMPLETE": "success",
    "DONE": "success",
    "SUCCESS": "success",
    "LOADING": "pending",
    "PENDING": "pending",
    "PROGRESS": "pending",
    "PUSH_PENDING": "pending",
    "QUEUED": "pending",
    "RECEIVED": "pending",
    "RETRY": "pending",
    "REVIEW_PENDING": "pending",
    "RUNNING": "pending",
    "STARTED": "pending",
    "FAILURE": "error",
}


@register.simple_tag
def status_box(status: Any, label: Any = None, detail: Any = None) -> SafeString:
    """Render a status pill, with the tone taken from the raw status so translated labels don't affect it.

    `detail` is appended in brackets, so a status that is costly to read only has to be read once.
    The same function is used from templates and from list cells.
    """
    label = label or status
    if detail:
        label = f"{label} ({detail})"
    return format_html(
        '<span class="status-box status-box--{}">{}</span>',
        STATUS_TONES.get(str(status).upper(), "neutral"),
        label,
    )
