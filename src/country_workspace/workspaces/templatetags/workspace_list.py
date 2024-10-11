import datetime
from typing import TYPE_CHECKING

from django.contrib.admin import ModelAdmin
from django.contrib.admin.templatetags.admin_list import ResultList as DjangoResultList
from django.contrib.admin.templatetags.admin_list import _coerce_field_name, result_hidden_fields
from django.contrib.admin.utils import display_for_field, display_for_value, label_for_field, lookup_field
from django.contrib.admin.views.main import ORDER_VAR
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Model
from django.db.models.constants import LOOKUP_SEP
from django.template import Library
from django.urls import NoReverseMatch
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .base import WorkspaceInclusionAdminNode
from .workspace_urls import add_preserved_filters

if TYPE_CHECKING:
    from ..changelist import WorkspaceChangeList

register = Library()


class ResultList(DjangoResultList):
    pass


def flex_field_label_for_field(column_name: str, model: "Model", model_admin: "ModelAdmin"):
    return column_name.replace("flex_fields__", ""), ""


def flex_field_lookup_field(field_name: str, result, model_admin: "ModelAdmin"):
    dict_key = field_name.replace("flex_fields__", "")
    f, attr, value = lookup_field(lambda o: o.flex_fields.get(dict_key), result, model_admin)
    return f, attr, value


def result_headers(cl: "WorkspaceChangeList"):  # noqa
    """
    Overrides standard Django behaviour to silent error if wrong columns have been configured
    """
    ordering_field_columns = cl.get_ordering_field_columns()
    for i, field_name in enumerate(cl.list_display):
        try:
            if field_name.startswith("flex_fields__"):
                text, attr = flex_field_label_for_field(field_name, cl.model, model_admin=cl.model_admin)
            else:
                text, attr = label_for_field(field_name, cl.model, model_admin=cl.model_admin, return_attr=True)
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
                        f'<input type="checkbox" id="action-toggle" ' f'aria-label="{aria_label}">'
                    ),
                    "class_attrib": mark_safe(' class="action-checkbox-column"'),  # nosec B308 B703
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
            "class_attrib": (format_html(' class="{}"', " ".join(th_classes)) if th_classes else ""),
        }


def items_for_result(cl, result, form):  # noqa
    """
    Generate the actual list of data.
    """

    def link_in_col(is_first, field_name, cl):
        if cl.list_display_links is None:
            return False
        if is_first and not cl.list_display_links:
            return True
        return field_name in cl.list_display_links

    first = True
    pk = cl.lookup_opts.pk.attname
    for field_index, field_name in enumerate(cl.list_display):
        empty_value_display = cl.model_admin.get_empty_value_display()
        row_classes = ["field-%s" % _coerce_field_name(field_name, field_index)]
        try:
            if field_name.startswith("flex_fields__"):
                f, attr, value = flex_field_lookup_field(field_name, result, cl.model_admin)
            else:
                f, attr, value = lookup_field(field_name, result, cl.model_admin)
        except ObjectDoesNotExist:
            result_repr = empty_value_display
        else:
            empty_value_display = getattr(attr, "empty_value_display", empty_value_display)
            if f is None or f.auto_created:
                if field_name == "action_checkbox":
                    row_classes = ["action-checkbox"]
                boolean = getattr(attr, "boolean", False)
                # Set boolean for attr that is a property, if defined.
                if isinstance(attr, property) and hasattr(attr, "fget"):
                    boolean = getattr(attr.fget, "boolean", False)
                result_repr = display_for_value(value, empty_value_display, boolean)
                if isinstance(value, (datetime.date, datetime.time)):
                    row_classes.append("nowrap")
            else:
                if isinstance(f.remote_field, models.ManyToOneRel):
                    field_val = getattr(result, f.name)
                    if field_val is None:
                        result_repr = empty_value_display
                    else:
                        result_repr = field_val
                else:
                    result_repr = display_for_field(value, f, empty_value_display)
                if isinstance(f, (models.DateField, models.TimeField, models.ForeignKey)):
                    row_classes.append("nowrap")
        row_class = mark_safe(' class="%s"' % " ".join(row_classes))  # nosec
        # If list_display_links not defined, add the link tag to the first field
        if link_in_col(first, field_name, cl):
            table_tag = "th" if first else "td"
            first = False

            # Display link to the result's change_view if the url exists, else
            # display just the result's representation.
            try:
                url = cl.url_for_result(result)
            except NoReverseMatch:
                link_or_text = result_repr
            else:
                url = add_preserved_filters({"preserved_filters": cl.preserved_filters, "opts": cl.opts}, url)
                # Convert the pk to something that can be used in JavaScript.
                # Problem cases are non-ASCII strings.
                if cl.to_field:
                    attr = str(cl.to_field)
                else:
                    attr = pk
                value = result.serializable_value(attr)
                link_or_text = format_html(
                    '<a href="{}"{}>{}</a>',
                    url,
                    (format_html(' data-popup-opener="{}"', value) if cl.is_popup else ""),
                    result_repr,
                )

            yield format_html("<{}{}>{}</{}>", table_tag, row_class, link_or_text, table_tag)
        else:
            # By default the fields come from ModelAdmin.list_editable, but if we pull
            # the fields out of the form instead of list_editable custom admins
            # can provide fields on a per request basis
            if (
                form
                and field_name in form.fields
                and not (field_name == cl.model._meta.pk.name and form[cl.model._meta.pk.name].is_hidden)
            ):
                bf = form[field_name]
                result_repr = mark_safe(str(bf.errors) + str(bf))  # nosec
            yield format_html("<td{}>{}</td>", row_class, result_repr)
    if form and not form[cl.model._meta.pk.name].is_hidden:
        yield format_html("<td>{}</td>", form[cl.model._meta.pk.name])


def results(cl):
    if cl.formset:
        for res, form in zip(cl.result_list, cl.formset.forms):
            yield ResultList(form, items_for_result(cl, res, form))
    else:
        for res in cl.result_list:
            yield ResultList(None, items_for_result(cl, res, None))


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
