import logging
import urllib.parse
from typing import Any

from django import template
from django.apps import apps
from django.contrib.admin import ModelAdmin
from django.contrib.admin.templatetags.admin_urls import (
    Resolver404,
    get_script_prefix,
    parse_qsl,
    resolve,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)
from django.db.models import Model
from django.db.models.options import Options
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)
register = template.Library()


@register.simple_tag()
def admin_url(obj: Model, **extra: dict[str, Any]) -> str:
    url = ""
    filters = ""
    if obj:
        try:
            if isinstance(obj, Model):
                if obj._meta.proxy_for_model:
                    opts = obj._meta.proxy_for_model._meta
                else:
                    opts = obj._meta
                url = reverse("admin:%s_%s_change" % (opts.app_label, opts.model_name), args=(obj.pk,))
            elif isinstance(obj, ModelAdmin):
                opts = obj.opts.proxy_for_model._meta
                url = reverse("admin:%s_%s_changelist" % (opts.app_label, opts.model_name))
            elif isinstance(obj, str):
                model = apps.get_model(obj)
                opts = model._meta
                url = reverse("admin:%s_%s_changelist" % (opts.app_label, opts.model_name))

            if extra:
                filters = urllib.parse.urlencode(extra)

            return mark_safe(  # noqa: S308
                f'<a class="admin-change-link" target="_admin" href="{url}?{filters}">'
                '<span class="icon icon-shield1"></span>'
                "</a>",
            )
        except NoReverseMatch as e:
            logger.exception(e)

    return ""


@register.filter
def workspace_urlname(value: Options, arg: str) -> str:
    return "workspace:%s_%s_%s" % (value.app_label, value.model_name, arg)


@register.filter
def admin_urlname(value: Options, arg: str) -> str:
    return "workspace:%s_%s_%s" % (value.app_label, value.model_name, arg)


@register.simple_tag(takes_context=True)
def add_preserved_filters(context: dict[str, Any], url: str, popup: bool = False, to_field: str | None = None) -> str:
    opts = context.get("opts")
    preserved_filters = context.get("preserved_filters")
    preserved_qsl = context.get("preserved_qsl")

    parsed_url = list(urlparse(url))
    parsed_qs = dict(parse_qsl(parsed_url[4]))
    merged_qs = {}

    if preserved_qsl:
        merged_qs.update(preserved_qsl)

    if opts and preserved_filters:
        preserved_filters = dict(parse_qsl(preserved_filters))

        match_url = "/%s" % unquote(url).partition(get_script_prefix())[2]
        try:
            match = resolve(match_url)
        except Resolver404:
            pass
        else:
            current_url = "%s:%s" % (match.app_name, match.url_name)
            changelist_url = "workspace:%s_%s_changelist" % (
                opts.app_label,
                opts.model_name,
            )
            if changelist_url == current_url and "_changelist_filters" in preserved_filters:
                preserved_filters = dict(parse_qsl(preserved_filters["_changelist_filters"]))

        merged_qs.update(preserved_filters)

    if popup:
        from django.contrib.admin.options import IS_POPUP_VAR

        merged_qs[IS_POPUP_VAR] = 1
    if to_field:
        from django.contrib.admin.options import TO_FIELD_VAR

        merged_qs[TO_FIELD_VAR] = to_field

    merged_qs.update(parsed_qs)

    parsed_url[4] = urlencode(merged_qs)
    return urlunparse(parsed_url)
