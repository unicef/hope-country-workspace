import io
from io import BytesIO
from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from hope_flex_fields.models import DataChecker, FlexField
from hope_flex_fields.xlsx import get_format_for_field

from country_workspace.models import Program
from country_workspace.workspaces.admin.actions.base import BaseActionForm

if TYPE_CHECKING:
    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin


class BulkUpdateForm(BaseActionForm):
    fields = forms.MultipleChoiceField(choices=[], widget=forms.CheckboxSelectMultiple())

    def __init__(self, *args, **kwargs):
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        self.fields["fields"].choices = [(name, name) for name, fld in checker.get_form()().fields.items()]


class Criteria:
    pass


class MinValueCriteria(Criteria):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        # {"validate": "integer", "criteria": "<", "value": 10}
        return {"criteria": ">", "value": self.value}


class MaxValueCriteria(Criteria):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        # {"validate": "integer", "criteria": "<", "value": 10}
        return {"criteria": "<", "value": self.value}


class MinMaxValueCriteria(Criteria):
    def __init__(self, min_value, max_value):
        self.min_value = min_value
        self.max_value = max_value

    def __str__(self):
        # {"validate": "decimal", "criteria": "between", "minimum": 0.1, "maximum": 0.5},
        return {"criteria": "between", "minimum": self.min_value, "maximum": self.max_value}


class ChoiceValueCriteria(Criteria):
    def __init__(self, values):
        self.values = values

    def __str__(self):
        return {"validate": "list", "source": self.values}


class XlsValidateRule:
    validate = ""

    def __init__(self, field: FlexField):
        self.field = field

    def __call__(self):
        return {}


class ValidateInteger(XlsValidateRule):
    validate = "integer"


class ValidateBool(XlsValidateRule):
    validate = "list"

    def __call__(self):
        return {"validate": "list", "source": ["", "True", "False"]}


class ValidateList(XlsValidateRule):
    validate = "list"

    def __call__(self):
        ch = self.field.get_merged_attrs().get("choices", [])
        if ch:
            return {"validate": "list", "source": [c[0] for c in ch]}
        return {}


TYPES = {
    forms.IntegerField: ValidateInteger,
    forms.ChoiceField: ValidateList,
    forms.BooleanField: ValidateBool,
}


def get_validation_for_field(fld: "FlexField"):
    validate = TYPES.get(fld.field.field_type, XlsValidateRule)(fld)
    return validate()


def dc_get_field(dc: "DataChecker", name) -> "FlexField":
    for fs in dc.members.all():
        for field in fs.fieldset.fields.filter():
            if field.name == name:
                return field


def create_xls_importer(queryset, dc: "DataChecker", columns: list[str]):
    import xlsxwriter

    out = BytesIO()
    workbook = xlsxwriter.Workbook(out, {"in_memory": True, "default_date_format": "yyyy/mm/dd"})

    header_format = workbook.add_format(
        {
            "bold": False,
            "font_color": "black",
            "font_size": 12,
            "font_name": "Arial",
            "align": "center",
            "valign": "vcenter",
            "indent": 1,
        }
    )

    header_format.set_bg_color("#DDDDDD")
    header_format.set_locked(True)
    header_format.set_align("center")
    header_format.set_bottom_color("black")
    worksheet = workbook.add_worksheet()
    worksheet.protect()
    worksheet.unprotect_range("B1:ZZ999", None)

    for i, fld_name in enumerate(columns):
        fld = dc_get_field(dc, fld_name)
        if fld:
            worksheet.write(0, i, fld.name, header_format)
            f = None
            if fmt := get_format_for_field(fld):
                f = workbook.add_format(fmt)
            worksheet.set_column(i, i, 40, f)
            if v := get_validation_for_field(fld):
                worksheet.data_validation(0, i, 999999, i, v)
        else:
            worksheet.write(0, i, fld_name, header_format)
    worksheet.freeze_panes(1, 0)

    for row, record in enumerate(queryset, 1):
        for col, fld in enumerate(columns):
            worksheet.write(row, col, getattr(record, fld, record.flex_fields.get(fld)))

    # worksheet.set_column(0,0, width=10, options={"locked": True})
    # worksheet.set_column(1, 9999, None, options={"locked": False})
    # worksheet.protect('password')
    # worksheet.unprotect_range('B:ZZZZ', None, 'password')

    workbook.close()
    out.seek(0)
    return out, workbook


def bulk_update_export_impl(
    records: "QuerySet[Beneficiary]", program: "Program", config: "dict[str, Any]"
) -> io.BytesIO:
    dc = program.get_checker_for(records.model)
    return create_xls_importer(records, dc, config["fields"])[0]


def bulk_update_export(model_admin: "BeneficiaryBaseAdmin", request, queryset):
    ctx = model_admin.get_common_context(request, title=_("Export data for bulk update"))
    ctx["checker"] = checker = model_admin.get_checker(request)
    form = BulkUpdateForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_export" in request.POST:
        if form.is_valid():
            config = {"fields": ["id"] + sorted(form.cleaned_data["fields"])}
            out = bulk_update_export_impl(queryset.all(), model_admin.get_selected_program(request), config)
            filename = "%s.xls" % queryset.model._meta.verbose_name_plural.lower().replace(" ", "_")
            response = HttpResponse(
                out.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = 'attachment;filename="%s"' % filename
            return response

    return render(request, "workspace/actions/bulk_update_export.html", ctx)
