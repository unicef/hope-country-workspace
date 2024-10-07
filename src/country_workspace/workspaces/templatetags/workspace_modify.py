from inspect import getfullargspec

from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row
from django.template.library import InclusionNode, parse_bits

register = template.Library()


class InclusionAdminNode(InclusionNode):
    """
    Template tag that allows its template to be overridden per model, per app,
    or globally.
    """

    def __init__(self, parser, token, func, template_name, takes_context=True):
        self.template_name = template_name
        params, varargs, varkw, defaults, kwonly, kwonly_defaults, _ = getfullargspec(
            func
        )
        bits = token.split_contents()
        args, kwargs = parse_bits(
            parser,
            bits[1:],
            params,
            varargs,
            varkw,
            defaults,
            kwonly,
            kwonly_defaults,
            takes_context,
            bits[0],
        )
        super().__init__(func, takes_context, args, kwargs, filename=None)

    def render(self, context):
        opts = context["opts"]
        app_label = opts.app_label.lower()
        object_name = opts.model_name
        # Load template for this render call. (Setting self.filename isn't
        # thread-safe.)
        context.render_context[self] = context.template.engine.select_template(
            [
                "workspace/%s/%s/%s" % (app_label, object_name, self.template_name),
                "workspace/%s/%s" % (app_label, self.template_name),
                "workspace/%s" % self.template_name,
            ]
        )
        return super().render(context)


@register.tag(name="submit_row")
def submit_row_tag(parser, token):
    return InclusionAdminNode(
        parser, token, func=submit_row, template_name="w_submit_line.html"
    )


#
# @register.tag(name="change_form_object_tools")
# def change_form_object_tools_tag(parser, token):
#     """Display the row of change form object tools."""
#     return InclusionAdminNode(
#         parser,
#         token,
#         func=lambda context: context,
#         template_name="change_form_object_tools.html",
#     )
#
#
# @register.filter
# def cell_count(inline_admin_form):
#     """Return the number of cells used in a tabular inline."""
#     count = 1  # Hidden cell with hidden 'id' field
#     for fieldset in inline_admin_form:
#         # Count all visible fields.
#         for line in fieldset:
#             for field in line:
#                 try:
#                     is_hidden = field.field.is_hidden
#                 except AttributeError:
#                     is_hidden = field.field["is_hidden"]
#                 if not is_hidden:
#                     count += 1
#     if inline_admin_form.formset.can_delete:
#         # Delete checkbox
#         count += 1
#     return count
