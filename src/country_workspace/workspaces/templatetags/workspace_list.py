from django.contrib.admin.templatetags.admin_list import (
    _coerce_field_name,
    result_hidden_fields,
    results,
)
from django.contrib.admin.utils import label_for_field
from django.contrib.admin.views.main import ORDER_VAR
from django.db.models.constants import LOOKUP_SEP
from django.template import Library
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .base import WorkspaceInclusionAdminNode

register = Library()


def result_headers(cl):  # noqa
    """
    Overrides standard Django behaviour to silent error if wrong columns have been configured
    """
    ordering_field_columns = cl.get_ordering_field_columns()
    for i, field_name in enumerate(cl.list_display):
        try:
            text, attr = label_for_field(
                field_name, cl.model, model_admin=cl.model_admin, return_attr=True
            )
        except AttributeError:
            continue
        is_field_sortable = cl.sortable_by is None or field_name in cl.sortable_by
        if attr:
            field_name = _coerce_field_name(field_name, i)
            # Potentially not sortable

            # if the field is the action checkbox: no sorting and special class
            if field_name == "action_checkbox":
                aria_label = _("Select all objects on this page for an action")
                yield {
                    "text": mark_safe(  # nosec B308 B703
                        f'<input type="checkbox" id="action-toggle" '
                        f'aria-label="{aria_label}">'
                    ),
                    "class_attrib": mark_safe(  # nosec B308 B703
                        ' class="action-checkbox-column"'
                    ),
                    "sortable": False,
                }
                continue

            admin_order_field = getattr(attr, "admin_order_field", None)
            # Set ordering for attr that is a property, if defined.
            if isinstance(attr, property) and hasattr(attr, "fget"):
                admin_order_field = getattr(attr.fget, "admin_order_field", None)
            if not admin_order_field and LOOKUP_SEP not in field_name:
                is_field_sortable = False

        if not is_field_sortable:
            # Not sortable
            yield {
                "text": text,
                "class_attrib": format_html(' class="column-{}"', field_name),
                "sortable": False,
            }
            continue

        # OK, it is sortable if we got this far
        th_classes = ["sortable", "column-{}".format(field_name)]
        order_type = ""
        new_order_type = "asc"
        sort_priority = 0
        # Is it currently being sorted on?
        is_sorted = i in ordering_field_columns
        if is_sorted:
            order_type = ordering_field_columns.get(i).lower()
            sort_priority = list(ordering_field_columns).index(i) + 1
            th_classes.append("sorted %sending" % order_type)
            new_order_type = {"asc": "desc", "desc": "asc"}[order_type]

        # build new ordering param
        o_list_primary = []  # URL for making this field the primary sort
        o_list_remove = []  # URL for removing this field from sort
        o_list_toggle = []  # URL for toggling order type for this field

        def make_qs_param(t, n):
            return ("-" if t == "desc" else "") + str(n)

        for j, ot in ordering_field_columns.items():
            if j == i:  # Same column
                param = make_qs_param(new_order_type, j)
                # We want clicking on this header to bring the ordering to the
                # front
                o_list_primary.insert(0, param)
                o_list_toggle.append(param)
                # o_list_remove - omit
            else:
                param = make_qs_param(ot, j)
                o_list_primary.append(param)
                o_list_toggle.append(param)
                o_list_remove.append(param)

        if i not in ordering_field_columns:
            o_list_primary.insert(0, make_qs_param(new_order_type, i))

        yield {
            "text": text,
            "sortable": True,
            "sorted": is_sorted,
            "ascending": order_type == "asc",
            "sort_priority": sort_priority,
            "url_primary": cl.get_query_string({ORDER_VAR: ".".join(o_list_primary)}),
            "url_remove": cl.get_query_string({ORDER_VAR: ".".join(o_list_remove)}),
            "url_toggle": cl.get_query_string({ORDER_VAR: ".".join(o_list_toggle)}),
            "class_attrib": (
                format_html(' class="{}"', " ".join(th_classes)) if th_classes else ""
            ),
        }


def result_list(cl):
    """
    Overridden to call our result_headers() instead of the Django's one
    """
    headers = list(result_headers(cl))
    num_sorted_fields = 0
    for h in headers:
        if h["sortable"] and h["sorted"]:
            num_sorted_fields += 1
    return {
        "cl": cl,
        "result_hidden_fields": list(result_hidden_fields(cl)),
        "result_headers": headers,
        "num_sorted_fields": num_sorted_fields,
        "results": list(results(cl)),
    }


@register.tag(name="result_list")
def result_list_tag(parser, token):
    """
    Overrides standard Django behaviour to use WorkspaceInclusionAdminNode
    """
    return WorkspaceInclusionAdminNode(
        parser,
        token,
        func=result_list,
        template_name="change_list_results.html",
        takes_context=False,
    )


@register.tag(name="change_list_object_tools")
def change_list_object_tools_tag(parser, token):
    """Display the row of change list object tools."""
    return WorkspaceInclusionAdminNode(
        parser,
        token,
        func=lambda context: context,
        template_name="change_list_object_tools.html",
    )
