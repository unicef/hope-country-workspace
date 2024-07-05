from typing import Any
from urllib.parse import urlencode

from django.template import Library
from django.utils.safestring import mark_safe

from adminfilters.utils import parse_bool

register = Library()


@register.simple_tag(takes_context=True)
def build_filter_url(
    context: dict[str, Any], field: str | None = None, value: str | None = None
) -> str:
    params = context["request"].GET.copy()
    if field:
        if value:
            params[field] = value
        elif field in params:
            del params[field]
    return "?%s" % urlencode(sorted(params.items()))


@register.filter("parse_bool")
def _parse_bool(value: Any) -> bool:
    return parse_bool(value)


@register.filter()
def as_bool_icon(value: Any) -> str:
    if parse_bool(value):
        snip = '<div class="icon icon-check1 text-green-400"></div>'
    else:
        snip = '<div class="icon icon-block text-red-400"></div>'
    return mark_safe(snip)


@register.filter()
def as_lock_icon(value: Any) -> str:
    if parse_bool(value):
        snip = '<div class="icon icon-lock1 text-red-400"></div>'
    else:
        snip = '<div class="icon icon-unlock1 text-green-400"></div>'

    return mark_safe(snip)


@register.filter()
def as_zip_icon(value: Any) -> str:
    if parse_bool(value):
        snip = '<div class="icon icon-zip1" style="color:#ffc400"></div>'
    else:
        snip = ""

    return mark_safe(snip)


@register.filter()
def as_icon(value: Any, cfg: str) -> str:
    icon, color_true, color_false = cfg.split(",")
    if parse_bool(value):
        snip = f'<div class="icon {icon} {color_true}"></div>'
    elif color_false:
        snip = f'<div class="icon {icon} {color_false}"></div>'
    else:
        snip = ""

    return mark_safe(snip)


@register.filter()
def as_group_icon(value: Any) -> str:
    if parse_bool(value):
        snip = '<div class="icon icon-group"></div>'
    else:
        snip = ""

    return mark_safe(snip)
