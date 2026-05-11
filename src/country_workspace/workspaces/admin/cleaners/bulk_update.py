import io
from collections.abc import Callable
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any
from django.db.models import Case, When, Value, Q, CharField

from constance import config as constance_config
from django import forms
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import EmailMessage
from django.forms.fields import DateField, DateTimeField
from django.utils import timezone
from django.db import transaction
from hope_flex_fields.models import DataChecker, FlexField
from hope_flex_fields.xlsx import get_format_for_field
from hope_smart_import.readers import open_xls
from xlsxwriter import Workbook
from xlsxwriter.format import Format
from xlsxwriter.worksheet import Worksheet
from country_workspace.models import AsyncJob, Program, Country
from country_workspace.models.base import Validable
from country_workspace.state import state
from country_workspace.storages import MEDIA_STORAGE
from country_workspace.workspaces.admin.cleaners.exceptions import BulkImportError, BulkImportFileProcessingError
from django.db.models import QuerySet

if TYPE_CHECKING:
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


ITERATOR_CHUNK_SIZE = 50


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


def _validate_date_format(value: str) -> bool:
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"]:
        try:
            naive_dt = datetime.strptime(value, fmt)  # noqa: DTZ007
            naive_dt.replace(tzinfo=timezone.get_current_timezone())
        except ValueError:
            continue
        else:
            return True
    return False


def _validate_datetime_format(value: str) -> bool:
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"]:
        try:
            naive_dt = datetime.strptime(value, fmt)  # noqa: DTZ007
            naive_dt.replace(tzinfo=timezone.get_current_timezone())
        except (ValueError, TypeError):
            continue
        else:
            return True
    return False


def validate_date_datetime_fields(row: dict, dc: DataChecker, line_number: int, errors: dict) -> None:
    for k, v in row.items():
        if v is None or v == "":
            continue

        fld = dc_get_field(dc=dc, name=k.split("__")[-1])
        if not fld or fld.definition.field_type not in (DateField, DateTimeField) or not isinstance(v, str):
            continue

        is_valid = _validate_date_format(v) if fld.definition.field_type == DateField else _validate_datetime_format(v)

        if not is_valid:
            field_type = "date" if fld.definition.field_type == DateField else "datetime"
            errors.setdefault(f"Invalid {field_type} format for field '{k}' on line", []).append(line_number)


def _get_cell_format(workbook: Workbook, field: FlexField) -> Format | None:
    if fmt := get_format_for_field(field):
        return workbook.add_format(fmt)
    return None


def _get_header_format(workbook: Workbook) -> Format:
    return workbook.add_format(
        {
            "bold": False,
            "font_color": "black",
            "font_size": 12,
            "font_name": "Arial",
            "align": "center",
            "valign": "vcenter",
            "indent": 1,
            "bg_color": "#DDDDDD",
            "locked": True,
            "bottom_color": "black",
        }
    )


def create_bulk_update_template(queryset: "QuerySet[Beneficiary]", program: Program, columns: list[str]) -> BytesIO:
    out = BytesIO()
    dc: DataChecker = program.get_checker_for(queryset.model)
    field_lookup = {field.name: field for _, field in dc.get_fields()}

    with Workbook(out, {"in_memory": True, "default_date_format": "yyyy/mm/dd"}) as workbook:
        header_format = _get_header_format(workbook)
        worksheet = workbook.add_worksheet()
        worksheet.protect()
        worksheet.unprotect_range("C1:ZZ999", None)

        field_to_choices = {}
        for i, fld_name in enumerate(columns):
            fld = field_lookup.get(fld_name)
            if fld:
                worksheet.write(0, i, fld.name, header_format)
                cell_format = _get_cell_format(workbook, fld)
                worksheet.set_column(i, i, 40, cell_format)
                if v := get_validation_for_field(fld):
                    worksheet.data_validation(0, i, 999999, i, v)
                if choices := _extract_choices_from_field(field=fld):
                    field_to_choices[fld.name] = choices

            else:
                worksheet.write(0, i, fld_name, header_format)

        worksheet.freeze_panes(1, 0)

        fmt = lambda v: ", ".join(map(str, v)) if isinstance(v, list | tuple) else str(v if v is not None else "")
        for row, record in enumerate(queryset.iterator(chunk_size=ITERATOR_CHUNK_SIZE), 1):
            for col, fld in enumerate(columns):
                value = getattr(record, fld, record.flex_fields.get(fld))
                worksheet.write(row, col, fmt(value))

        _add_choices_worksheet(workbook, field_to_choices, columns)

    out.seek(0)
    return out


def _extract_choices_from_field(field: FlexField) -> list[Any]:
    flatten = lambda elements: [el[0] for el in elements]

    if (choices := field.attrs.get("choices")) or (choices := field.definition.attrs.get("choices")):
        return flatten(choices)

    if field.name in ("admin1", "admin2", "admin3", "admin4"):
        return field.definition.field_type().choices

    return []


def _get_country_choices() -> list:
    return list(Country.objects.only("iso_code2", "name").order_by("name"))


def _write_country_choices(worksheet: Worksheet, start_row: int) -> int:
    countries = _get_country_choices()
    row = start_row
    for i, country in enumerate(countries):
        if i == 0:
            worksheet.write(row, 0, "country")
        worksheet.write(row, 1, country.iso_code2)
        worksheet.write(row, 2, country.name)
        row += 1
    return row


def _write_headers(worksheet: Worksheet, header_format: Format) -> None:
    headers = ["Field Name", "Choices", "Comment"]
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)


def _parse_choice(choice: Any) -> tuple[str, str]:
    if isinstance(choice, tuple | list):
        value = choice[0]
        comment = choice[1] if len(choice) > 1 else ""
    else:
        value = choice
        comment = "an empty string" if choice == "" else ""
    return value, comment


def _write_field_choices(worksheet: Worksheet, field_to_choices: dict[str, list[Any]], start_row: int) -> int:
    row = start_row
    for field, choices in field_to_choices.items():
        for i, choice in enumerate(choices):
            if i == 0:
                worksheet.write(row, 0, field)

            value, comment = _parse_choice(choice)
            worksheet.write(row, 1, value)
            if comment:
                worksheet.write(row, 2, comment)
            row += 1

        row += 1  # Blank line between different fields
    return row


def _add_choices_worksheet(workbook: Workbook, field_to_choices: dict[str, list[Any]], columns: list) -> None:
    choices_ws = workbook.add_worksheet("Choices")
    bold_header = _get_header_format(workbook)

    _write_headers(choices_ws, bold_header)
    row = 1

    if field_to_choices:
        row = _write_field_choices(choices_ws, field_to_choices, start_row=row)

    if any("country" in col.lower() for col in columns):
        row = _write_country_choices(choices_ws, start_row=row)

    # Set column widths
    choices_ws.set_column(0, 0, 20)
    choices_ws.set_column(1, 1, 25)
    choices_ws.set_column(2, 2, 20)


def _send_template_email(job: AsyncJob, out: BytesIO, filename: str) -> None:
    email = EmailMessage(
        subject="Bulk update export",
        body="Please find the requested bulk update template attached.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[job.config["send_to"]],
    )
    out.seek(0)
    email.attach(filename, out.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    email.send()


def export_bulk_update_template(job: AsyncJob) -> str:
    with state.set(tenant=job.program.country_office, program=job.program):
        model = apps.get_model(job.config["model_name"])
        queryset = _get_queryset_with_is_valid_annotation(model, job)

        out = create_bulk_update_template(queryset, job.program, job.config["columns"])
        filename = f"bulk_update_template/{job.program.pk}/{job.owner.pk}/{job.config['model_name']}.xlsx"
        filepath = MEDIA_STORAGE.save(filename, out)

        _send_template_email(job, out, filename)

        job.file = filepath
        job.save(update_fields=["file"])

        return filepath


def _get_queryset_with_is_valid_annotation(model: Validable, job: AsyncJob) -> QuerySet:
    qs = model.objects.filter(pk__in=job.config["pks"]).defer(
        "raw_data",
        "system_fields",
        "flex_files",
    )
    if (columns := job.config.get("columns")) and ("is_valid" in columns and "errors" in columns):
        qs = qs.annotate(
            is_valid=Case(
                When(last_checked__isnull=True, then=Value("Not Checked")),
                When(Q(last_checked__isnull=False) & Q(errors={}), then=Value("True")),
                default=Value("False"),
                output_field=CharField(),
            )
        )

    return qs


def import_bulk_update_file(job: AsyncJob, entity_getter: Callable[[int], Any]) -> dict[str, Any]:  # noqa: C901
    total = {"processed": 0, "not_found": [], "errors": {}}
    version_check_enabled = constance_config.CONCURRENCY_GUARD
    if version_check_enabled:
        total["version_mismatch"] = []

    try:
        file_data = job.file.read()
        rows = open_xls(io.BytesIO(file_data))

        with transaction.atomic():
            for line_number, row_data in enumerate(rows, start=1):
                try:
                    if not row_data or all(v in (None, "", []) for v in row_data.values()):
                        continue

                    entity_id = int(row_data.pop("id"))
                    entity = entity_getter(entity_id)

                    if version_check_enabled:
                        version = int(row_data.pop("version"))
                        if entity.version != version:
                            total["version_mismatch"].append(entity_id)
                            continue

                    if row_data:
                        dc: DataChecker = job.program.get_checker_for(entity.__class__)
                        validate_date_datetime_fields(row_data, dc, line_number, total["errors"])
                        validate_individual_reference_ids(row_data, line_number, total["errors"])

                        entity.flex_fields.update(**row_data)
                        entity.errors = {}
                        entity.last_checked = None
                        entity.save(update_fields=["flex_fields", "errors", "last_checked", "last_modified"])
                        total["processed"] += 1

                except (KeyError, ValueError):
                    total["errors"].setdefault("Invalid data on line", []).append(line_number)
                except ObjectDoesNotExist:
                    total["not_found"].append(entity_id)
                except Exception as e:  # noqa: BLE001
                    total["errors"].setdefault("Processing errors", []).append(f"Line {line_number}: {e}")

            if total["errors"]:
                raise BulkImportError(total["errors"])  # noqa: TRY301

    except Exception as e:  # noqa: BLE001
        raise BulkImportFileProcessingError(str(e))

    return total


def _validate_integer(value: str, field: str, line_number: int, errors: dict) -> None:
    try:
        int(value)
    except (ValueError, TypeError):
        errors.setdefault(f"Invalid data for {field} field. Must be of integer type", []).append(line_number)


def validate_individual_reference_ids(row_data: dict, line_number: int, errors: dict) -> None:
    required_fields = ("head_of_household_id", "primary_collector_id")
    optional_fields = ("alternate_collector_id",)

    sheet_fields = row_data.keys()
    for field in required_fields:
        if field not in sheet_fields:
            continue
        if not (value := row_data.get(field)):
            errors.setdefault(f"Invalid data. {field} field is required", []).append(line_number)
        else:
            _validate_integer(value, field, line_number, errors)

    for field in optional_fields:
        if field not in sheet_fields:
            continue
        if value := row_data.get(field):  # only validate if present
            _validate_integer(value, field, line_number, errors)


def import_individual_updates(job: AsyncJob) -> dict[str, Any]:
    return import_bulk_update_file(job, lambda _id: job.program.individuals.get(id=_id))


def import_household_updates(job: AsyncJob) -> dict[str, Any]:
    return import_bulk_update_file(job, lambda _id: job.program.households.get(id=_id))
