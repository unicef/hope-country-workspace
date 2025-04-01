import io
from collections.abc import Callable
from io import BytesIO
from typing import TYPE_CHECKING, Any

from constance import config as constance_config
from django import forms
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from hope_flex_fields.models import DataChecker, FlexField
from hope_flex_fields.xlsx import get_format_for_field
from hope_smart_import.readers import open_xls
from xlsxwriter import Workbook

from country_workspace.models import AsyncJob, Program
from country_workspace.storages import MEDIA_STORAGE

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from country_workspace.types import Beneficiary


"""
# class Criteria:
#     pass
#
#
# class MinValueCriteria(Criteria):
#     def __init__(self, value):
#         self.value = value
#
#     def __str__(self):
#         # {"validate": "integer", "criteria": "<", "value": 10}
#         return {"criteria": ">", "value": self.value}
#
#
# class MaxValueCriteria(Criteria):
#     def __init__(self, value):
#         self.value = value
#
#     def __str__(self):
#         # {"validate": "integer", "criteria": "<", "value": 10}
#         return {"criteria": "<", "value": self.value}
#
#
# class MinMaxValueCriteria(Criteria):
#     def __init__(self, min_value, max_value):
#         self.min_value = min_value
#         self.max_value = max_value
#
#     def __str__(self):
#         # {"validate": "decimal", "criteria": "between", "minimum": 0.1, "maximum": 0.5},
#         return {"criteria": "between", "minimum": self.min_value, "maximum": self.max_value}
#
#
# class ChoiceValueCriteria(Criteria):
#     def __init__(self, values):
#         self.values = values
#
#     def __str__(self):
#         return {"validate": "list", "source": self.values}
"""


class XlsValidateRule:
    validate = ""

    def __init__(self, field: FlexField) -> None:
        self.field = field

    def __call__(self) -> dict[str, Any]:
        return {}


class ValidateInteger(XlsValidateRule):
    validate = "integer"

    def __call__(self) -> dict[str, Any]:
        return {"validate": "integer"}


class ValidateBool(XlsValidateRule):
    validate = "list"

    def __call__(self) -> dict[str, Any]:
        return {"validate": "list", "source": ["", "True", "False"]}


class ValidateList(XlsValidateRule):
    validate = "list"

    def __call__(self) -> dict[str, Any]:
        ch = self.field.get_merged_attrs().get("choices", [])
        if ch:
            return {"validate": "list", "source": [c[0] for c in ch]}
        return {}


TYPES = {
    forms.IntegerField: ValidateInteger,
    forms.ChoiceField: ValidateList,
    forms.BooleanField: ValidateBool,
}


def get_validation_for_field(fld: "FlexField") -> dict[str, Any]:
    validate = TYPES.get(fld.definition.field_type, XlsValidateRule)(fld)
    return validate()


def dc_get_field(dc: "DataChecker", name: str) -> "FlexField | None":
    for fs in dc.members.all():
        for field in fs.fieldset.fields.filter():
            if field.name == name:
                return field
    return None


def create_xls_importer(
    queryset: "QuerySet[Beneficiary]",
    program: Program,
    columns: list[str],
) -> tuple[io.BytesIO, Workbook]:
    out = BytesIO()
    dc: DataChecker = program.get_checker_for(queryset.model)

    workbook = Workbook(out, {"in_memory": True, "default_date_format": "yyyy/mm/dd"})
    header_format = workbook.add_format(
        {
            "bold": False,
            "font_color": "black",
            "font_size": 12,
            "font_name": "Arial",
            "align": "center",
            "valign": "vcenter",
            "indent": 1,
        },
    )
    header_format.set_bg_color("#DDDDDD")
    header_format.set_locked(True)
    header_format.set_align("center")
    header_format.set_bottom_color("black")
    worksheet = workbook.add_worksheet()
    worksheet.protect()
    worksheet.unprotect_range("C1:ZZ999", None)

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

    workbook.close()
    out.seek(0)
    return out, workbook


def bulk_update_export_template(job: AsyncJob) -> bytes:
    model = apps.get_model(job.config["model_name"])
    queryset = model.objects.filter(pk__in=job.config["pks"])
    filename = "bulk_update_export_template/%s/%s/%s.xlsx" % (job.program.pk, job.owner.pk, job.config["model_name"])
    out, __ = create_xls_importer(queryset, job.program, job.config["columns"])
    path = MEDIA_STORAGE.save(filename, out)
    job.file = path
    job.save()
    return path


def bulk_update_collection(job: AsyncJob, collection_getter: Callable[[int], Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"not_found": []}
    version_check = constance_config.CONCURRENCY_GUARD
    if version_check:
        result["version_mismatch"] = []
    errors = {}

    file_data = job.file.read()
    rows = open_xls(io.BytesIO(file_data), start_at=0)
    for line_number, row in enumerate(rows, start=1):
        try:
            _id = int(row.pop("id"))
            entity = collection_getter(_id)
        except (KeyError, ValueError):
            errors.setdefault("Invalid or missing 'id' on line", []).append(line_number)
            continue
        except ObjectDoesNotExist:
            result["not_found"].append(_id)
            continue

        if version_check:
            try:
                _version = int(row.pop("version"))
            except (KeyError, ValueError):
                errors.setdefault("Invalid or missing 'version' on line", []).append(line_number)
                continue

            if entity.version != _version:
                result["version_mismatch"].append(_id)
                continue

        entity.flex_fields.update(**row)
        entity.save()

    if errors:
        result["errors"] = errors

    return result


def bulk_update_individual(job: AsyncJob) -> dict[str, Any]:
    program = job.program
    return bulk_update_collection(job, lambda _id: program.individuals.get(id=_id))


def bulk_update_household(job: AsyncJob) -> dict[str, Any]:
    program = job.program
    return bulk_update_collection(job, lambda _id: program.households.get(id=_id))
