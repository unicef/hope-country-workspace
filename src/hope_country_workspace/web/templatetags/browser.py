from typing import Any, Dict

from django.template import Library

register = Library()


@register.simple_tag(takes_context=True)
def is_media_supported(context: Dict[str, Any], content_type: str) -> bool:
    if content_type in ["text/csv"]:
        return False
    if content_type.startswith("text/"):
        return True
    if content_type in [
        "application/pdf",
        "application/json",
    ]:
        return True
    return content_type in context["request"].META["HTTP_ACCEPT"]
