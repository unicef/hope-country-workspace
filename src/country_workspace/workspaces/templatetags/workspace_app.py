import re

from django.template import Library, Node, NodeList
from django.template.base import Parser, Token
from django.template.context import Context
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from country_workspace import VERSION
from country_workspace.workspaces.icons import ICONS

register = Library()

SEPARATOR = re.compile("&rsaquo;|\u203a")
ADMIN_LINK = re.compile(r'<a class="admin-change-link".*?</a>', re.DOTALL)


@register.simple_tag
def app_version() -> str:
    return VERSION


@register.simple_tag
def icon(name: str, css_class: str = "") -> str:
    """Render a Material icon from ICONS as inline SVG, sized 1em and coloured by `currentColor`."""
    return mark_safe(  # noqa: S308
        f'<svg class="icon {css_class}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">'
        f"{ICONS[name]}</svg>"
    )


class PageHeadingNode(Node):
    def __init__(self, nodelist: NodeList) -> None:
        self.nodelist = nodelist

    def render(self, context: Context) -> str:
        segments = [s.strip() for s in SEPARATOR.split(self.nodelist.render(context))]
        segments = [s for s in segments if s]
        if not segments:
            return render_to_string("workspace/includes/page_heading.html", {"title": ""})
        *crumbs, title = segments
        return render_to_string(
            "workspace/includes/page_heading.html",
            {
                "crumbs": [mark_safe(ADMIN_LINK.sub("", c).strip()) for c in crumbs],  # noqa: S308
                "title": mark_safe(ADMIN_LINK.sub("", title).strip()),  # noqa: S308
                "flags": mark_safe("".join(ADMIN_LINK.findall(title))),  # noqa: S308
            },
        )


@register.tag
def page_heading(parser: Parser, token: Token) -> PageHeadingNode:
    """Split a "&rsaquo; crumb &rsaquo; crumb &rsaquo; title" page title into HOPE's breadcrumbs, title and admin flag.

    Earlier segments become breadcrumbs without their admin stars; the last is the title, and its admin star is kept
    next to it, like HOPE's PageHeader `flags`.
    """
    nodelist = parser.parse(("endpage_heading",))
    parser.delete_first_token()
    return PageHeadingNode(nodelist)
