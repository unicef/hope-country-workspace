from io import BytesIO
from types import TracebackType
from typing import TYPE_CHECKING, Final, Self

from xlsxwriter import Workbook
from xlsxwriter.utility import xl_range_abs

from country_workspace.state import state

from .columns import Column, Properties, build_columns, strict_validation
from .exceptions import NoDataCheckerError
from .layout import SheetPlan, get_sheet_plans

if TYPE_CHECKING:
    from xlsxwriter.format import Format
    from xlsxwriter.worksheet import Worksheet

    from country_workspace.models import Program

CHOICES_SHEET_NAME: Final[str] = "Choices"
CHOICES_COLUMNS_PER_LIST: Final[int] = 2  # values, then their labels
LAST_ROW: Final[int] = 1_048_575
MIN_COLUMN_WIDTH: Final[int] = 18
COLUMN_WIDTH_PADDING: Final[int] = 4
NOTE_OPTIONS: Final[Properties] = {"x_scale": 2, "y_scale": 2}

HEADER_FORMAT: Final[Properties] = {
    "bold": True,
    "align": "center",
    "valign": "vcenter",
    "bg_color": "#DDDDDD",
    "border": 1,
}
REQUIRED_HEADER_FORMAT: Final[Properties] = {**HEADER_FORMAT, "bg_color": "#FFE699"}


class ChoicesSheet:
    """Hidden sheet with the dropdown lists, since Excel caps inline lists at 255 characters."""

    def __init__(self) -> None:
        self._lists: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def add(self, title: str, choices: tuple[tuple[str, str], ...]) -> str:
        """Register a list and return the range its values will occupy."""
        value_col = len(self._lists) * CHOICES_COLUMNS_PER_LIST
        self._lists.append((title, choices))
        return f"={CHOICES_SHEET_NAME}!{xl_range_abs(1, value_col, len(choices), value_col)}"

    def write(self, workbook: Workbook) -> None:
        if not self._lists:
            return
        worksheet = workbook.add_worksheet(CHOICES_SHEET_NAME)
        for index, (title, choices) in enumerate(self._lists):
            value_col = index * CHOICES_COLUMNS_PER_LIST
            label_col = value_col + 1
            worksheet.write_string(0, value_col, title)
            worksheet.write_string(0, label_col, f"{title} (label)")
            for row, (value, label) in enumerate(choices, start=1):
                # text, as the import compares values as strings
                worksheet.write_string(row, value_col, value)
                worksheet.write_string(row, label_col, label)
        worksheet.hide()


class TemplateWriter:
    """Builds the workbook: data sheets in the order added, then the hidden choices sheet."""

    def __init__(self) -> None:
        self._buffer = BytesIO()
        self._workbook = Workbook(self._buffer, {"in_memory": True})
        self._formats: dict[tuple, Format] = {}
        self._choices = ChoicesSheet()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self._choices.write(self._workbook)
        self._workbook.close()

    def result(self) -> BytesIO:
        """Return the finished file; only available once the writer has been exited."""
        self._buffer.seek(0)
        return self._buffer

    def add_sheet(self, plan: SheetPlan, columns: list[Column]) -> None:
        worksheet = self._workbook.add_worksheet(plan.name.value)
        for index, column in enumerate(columns):
            self._write_column(worksheet, plan, index, column)
        worksheet.freeze_panes(1, 0)

    def _format(self, properties: Properties) -> "Format":
        key = tuple(sorted(properties.items()))
        if key not in self._formats:
            self._formats[key] = self._workbook.add_format(dict(properties))
        return self._formats[key]

    def _write_column(self, worksheet: "Worksheet", plan: SheetPlan, index: int, column: Column) -> None:
        header_format = REQUIRED_HEADER_FORMAT if column.required else HEADER_FORMAT
        worksheet.write_string(0, index, column.name, self._format(header_format))
        worksheet.write_comment(0, index, column.note, dict(NOTE_OPTIONS))

        constraint = column.constraint
        cell_format = self._format(constraint.cell_format) if constraint.cell_format else None
        worksheet.set_column(index, index, max(len(column.name) + COLUMN_WIDTH_PADDING, MIN_COLUMN_WIDTH), cell_format)

        validation = constraint.validation
        if constraint.choices:
            source = self._choices.add(f"{plan.name.value}.{column.name}", constraint.choices)
            if constraint.dropdown:
                validation = strict_validation("list", source=source)
        if validation:
            worksheet.data_validation(1, index, LAST_ROW, index, dict(validation))


def build_import_template(program: "Program") -> BytesIO:
    plans = get_sheet_plans(program)
    if not plans:
        raise NoDataCheckerError("The programme has no data checker to build an import template from.")

    with state.set(tenant=program.country_office, program=program), TemplateWriter() as writer:
        for plan in plans:
            writer.add_sheet(plan, build_columns(plan))
    return writer.result()
