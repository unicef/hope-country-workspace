from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row

from .base import WorkspaceInclusionAdminNode

register = template.Library()


@register.tag(name="submit_row")
def submit_row_tag(parser, token):
    return WorkspaceInclusionAdminNode(
        parser, token, func=submit_row, template_name="w_submit_line.html"
    )
