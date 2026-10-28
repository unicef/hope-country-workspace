from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import singledispatch
from typing import Any, Final

from django import forms
from django.utils.translation import gettext as _

from country_workspace.utils.flex_fields import CustomMultipleChoiceField

from .layout import CHOICES_SHEET_NAME, SheetPlan, SheetSpec

Properties = Mapping[str, Any]

MIN_DATE: Final[date] = date(1900, 1, 1)
MAX_NOTE_VALUES: Final[int] = 15
# xlsxwriter refuses a numeric validation without criteria: "any number" is a bound no real value reaches
UNBOUNDED_MINIMUM: Final[int] = -(10**15)

TEXT_FORMAT: Final[Properties] = {"num_format": "@"}  # keeps leading zeros and "+" of phone/document numbers
DATE_FORMAT: Final[Properties] = {"num_format": "yyyy-mm-dd"}
DATETIME_FORMAT: Final[Properties] = {"num_format": "yyyy-mm-dd hh:mm"}


def strict_validation(validate: str, **options: Any) -> Properties:
    """Build a validation that rejects non-compliant input instead of just warning."""
    return {"validate": validate, "error_type": "stop", **options}


@dataclass(frozen=True)
class Constraint:
    """What a sheet column enforces on its cells, derived from a data checker field."""

    cell_format: Properties | None = None
    validation: Properties | None = None
    choices: tuple[tuple[str, str], ...] = ()
    dropdown: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Column:
    name: str
    required: bool = False
    notes: tuple[str, ...] = ()
    constraint: Constraint = field(default_factory=Constraint)

    @property
    def note(self) -> str:
        return "\n".join(self.notes)


@singledispatch
def constrain(form_field: forms.Field) -> Constraint:
    """Pick the constraint of a checker field; the most specific registered field class wins."""
    return Constraint(cell_format=TEXT_FORMAT)


@constrain.register(forms.FileField)
def _constrain_file(form_field: forms.FileField) -> Constraint:
    return Constraint(
        notes=(
            _(
                'Insert the picture over the cell ("Place over cells", not "Place in cell"), '
                "with its top-left corner inside the cell."
            ),
        )
    )


@constrain.register(forms.ModelChoiceField)
def _constrain_model_choice(form_field: forms.ModelChoiceField) -> Constraint:
    return Constraint(cell_format=TEXT_FORMAT)


@constrain.register(forms.ChoiceField)
def _constrain_choice(form_field: forms.ChoiceField) -> Constraint:
    return _choice_constraint(form_field, dropdown=True)


@constrain.register(forms.MultipleChoiceField)
def _constrain_multiple_choice(form_field: forms.MultipleChoiceField) -> Constraint:
    return _choice_constraint(form_field, dropdown=False)


@constrain.register(CustomMultipleChoiceField)
def _constrain_parsed_multiple_choice(form_field: CustomMultipleChoiceField) -> Constraint:
    """Only this field parses a cell holding several values."""
    return _choice_constraint(
        form_field,
        dropdown=False,
        notes=(_("Several values can be given, separated by a comma."),),
    )


@constrain.register(forms.BooleanField)
def _constrain_boolean(form_field: forms.BooleanField) -> Constraint:
    return Constraint(validation=strict_validation("list", source=["True", "False"]))


@constrain.register(forms.IntegerField)
def _constrain_integer(form_field: forms.IntegerField) -> Constraint:
    return Constraint(validation=_numeric_validation("integer", form_field))


@constrain.register(forms.DecimalField)
@constrain.register(forms.FloatField)
def _constrain_decimal(form_field: forms.Field) -> Constraint:
    return Constraint(validation=_numeric_validation("decimal", form_field))


@constrain.register(forms.DateTimeField)
def _constrain_datetime(form_field: forms.DateTimeField) -> Constraint:
    return Constraint(cell_format=DATETIME_FORMAT)


@constrain.register(forms.DateField)
def _constrain_date(form_field: forms.DateField) -> Constraint:
    validation = strict_validation(
        "date",
        criteria=">=",
        value=MIN_DATE,
        error_title=_("Invalid date"),
        error_message=_("Enter a valid date, e.g. 2024-01-31."),
    )
    return Constraint(cell_format=DATE_FORMAT, validation=validation)


def _choice_pairs(choices: Iterable[tuple[Any, Any]]) -> tuple[tuple[str, str], ...]:
    """Flatten option groups and drop the empty option: an empty cell already means "no value"."""
    pairs: list[tuple[str, str]] = []
    for value, label in choices:
        if isinstance(label, list | tuple):
            pairs.extend(_choice_pairs(label))
        elif value not in ("", None):
            pairs.append((str(value), str(label)))
    return tuple(pairs)


def _choice_constraint(form_field: forms.ChoiceField, *, dropdown: bool, notes: tuple[str, ...] = ()) -> Constraint:
    choices = _choice_pairs(form_field.choices)
    allowed = ()
    if choices:
        shown = ", ".join(value for value, _label in choices[:MAX_NOTE_VALUES])
        more = ", ..." if len(choices) > MAX_NOTE_VALUES else ""
        allowed = (
            _("Allowed values: %(values)s\nAll of them, with their labels, are listed in the %(sheet)s sheet.")
            % {"values": shown + more, "sheet": CHOICES_SHEET_NAME},
        )
    return Constraint(
        cell_format=TEXT_FORMAT,
        choices=choices,
        dropdown=dropdown and bool(choices),
        notes=(*allowed, *notes),
    )


def _numeric_validation(kind: str, form_field: forms.Field) -> Properties:
    minimum = getattr(form_field, "min_value", None)
    maximum = getattr(form_field, "max_value", None)
    match minimum, maximum:
        case None, None:
            return strict_validation(kind, criteria=">=", value=UNBOUNDED_MINIMUM)
        case _, None:
            return strict_validation(kind, criteria=">=", value=minimum)
        case None, _:
            return strict_validation(kind, criteria="<=", value=maximum)
        case _:
            return strict_validation(kind, criteria="between", minimum=minimum, maximum=maximum)


def _field_notes(name: str, form_field: forms.Field) -> tuple[str, ...]:
    label = str(form_field.label or name)
    return (label, str(form_field.help_text)) if form_field.help_text else (label,)


def describe_field(name: str, form_field: forms.Field) -> Column:
    constraint = constrain(form_field)
    return Column(
        name=name,
        required=form_field.required,
        notes=(*_field_notes(name, form_field), *constraint.notes),
        constraint=constraint,
    )


def _reference_column(name: str, form_field: forms.Field, spec: SheetSpec) -> Column:
    """Ids are free-form values of another sheet, so the checker field must not constrain them."""
    return Column(
        name=name,
        required=form_field.required,
        notes=(*_field_notes(name, form_field), str(spec.reference_note)),
    )


def build_columns(plan: SheetPlan) -> list[Column]:
    """Id columns first, then the fields of the checker (minus the ones already provided as ids)."""
    spec = plan.spec
    columns = [Column(id_column.name, required=True, notes=(str(id_column.note),)) for id_column in spec.id_columns]
    provided = {column.name for column in columns}

    for name, form_field in plan.checker.get_form_class().base_fields.items():
        if (header := f"{spec.prefix}{name}") in provided:
            continue
        if name in spec.reference_fields:
            columns.append(_reference_column(header, form_field, spec))
        else:
            columns.append(describe_field(header, form_field))
    return columns
