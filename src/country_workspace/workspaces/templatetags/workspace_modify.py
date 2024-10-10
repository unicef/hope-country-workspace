from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row

from .base import WorkspaceInclusionAdminNode

register = template.Library()


@register.tag(name="submit_row")
def submit_row_tag(parser, token):
    return WorkspaceInclusionAdminNode(
        parser, token, func=submit_row, template_name="w_submit_line.html"
    )


@register.tag(name="change_form_object_tools")
def change_form_object_tools_tag(parser, token):
    """Display the row of change form object tools."""
    return WorkspaceInclusionAdminNode(
        parser,
        token,
        func=lambda context: context,
        template_name="change_form_object_tools.html",
    )
