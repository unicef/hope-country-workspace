from typing import Any

from django.template import Library

register = Library()

STATUS_TONES = {
    "ACTIVE": "success",
    "DONE": "success",
    "SUCCESS": "success",
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


@register.inclusion_tag("workspace/includes/status_box.html")
def status_box(status: Any, label: Any = None) -> dict[str, Any]:
    """Render a status pill, with the tone taken from the raw status so translated labels don't affect it."""
    return {"tone": STATUS_TONES.get(str(status).upper(), "neutral"), "label": label or status}
