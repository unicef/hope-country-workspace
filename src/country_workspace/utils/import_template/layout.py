from typing import TYPE_CHECKING, Final, Literal, NamedTuple

from django.utils.translation import gettext_lazy as _

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.datasources.rdi.config import SheetName

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise
    from hope_flex_fields.models import DataChecker

    from country_workspace.models import Program

HOUSEHOLD_ID_COLUMN: Final[str] = "household_id"
INDIVIDUAL_ID_COLUMN: Final[str] = "individual_id"
PEOPLE_PREFIX: Final[str] = "pp_"
PEOPLE_ID_COLUMN: Final[str] = f"{PEOPLE_PREFIX}index_id"


class IdColumn(NamedTuple):
    name: str
    note: "StrOrPromise"


class SheetSpec(NamedTuple):
    """What a sheet looks like, independently of the programme it is generated for."""

    name: SheetName
    checker_attr: Literal["household_checker", "individual_checker"]
    id_columns: tuple[IdColumn, ...]
    prefix: str = ""
    # checker fields holding the id of a record of another sheet instead of a value
    reference_fields: tuple[str, ...] = ()
    reference_note: "StrOrPromise" = ""


HOUSEHOLDS = SheetSpec(
    name=SheetName.HOUSEHOLDS,
    checker_attr="household_checker",
    id_columns=(IdColumn(HOUSEHOLD_ID_COLUMN, _("Unique identifier of the household within this file.")),),
    reference_fields=tuple(HOUSEHOLD_ROLE_REF_FIELDS),
    reference_note=_("Identifier of the person in the Individuals sheet."),
)

INDIVIDUALS = SheetSpec(
    name=SheetName.INDIVIDUALS,
    checker_attr="individual_checker",
    id_columns=(
        IdColumn(INDIVIDUAL_ID_COLUMN, _("Unique identifier of the individual within this file.")),
        IdColumn(
            HOUSEHOLD_ID_COLUMN,
            _(
                "Identifier of the household in the Households sheet. "
                "Use 0 for an individual without a household (e.g. an external collector)."
            ),
        ),
    ),
)

PEOPLE = SheetSpec(
    name=SheetName.PEOPLE,
    checker_attr="individual_checker",
    id_columns=(IdColumn(PEOPLE_ID_COLUMN, _("Unique identifier of the person within this file.")),),
    prefix=PEOPLE_PREFIX,
)

MASTER_DETAIL_SHEETS: Final[tuple[SheetSpec, ...]] = (HOUSEHOLDS, INDIVIDUALS)
PEOPLE_ONLY_SHEETS: Final[tuple[SheetSpec, ...]] = (PEOPLE,)


class SheetPlan(NamedTuple):
    """A sheet to generate: its spec and the data checker of the programme providing the columns."""

    spec: SheetSpec
    checker: "DataChecker"

    @property
    def name(self) -> SheetName:
        return self.spec.name


def _is_master_detail(program: "Program") -> bool:
    return bool(program.beneficiary_group and program.beneficiary_group.master_detail)


def get_sheet_plans(program: "Program") -> list[SheetPlan]:
    specs = MASTER_DETAIL_SHEETS if _is_master_detail(program) else PEOPLE_ONLY_SHEETS
    plans = [SheetPlan(spec, getattr(program, spec.checker_attr)) for spec in specs]
    return [plan for plan in plans if plan.checker]
