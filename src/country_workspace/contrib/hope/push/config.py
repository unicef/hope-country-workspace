import re
from collections.abc import Callable
from typing import Any, TypedDict, ReadOnly, Final
from enum import StrEnum, auto

from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


type Beneficiary = CountryHousehold | CountryIndividual
type Serializer = Callable[[list[dict]], Any]

# Matches tags like: IND-25-0000.0051
IND_TAG_RE = re.compile(r"^IND(?:-\d+)+\.\d+$")
ROLE_FIELDS: Final[tuple[str, ...]] = ("head_of_household", "primary_collector", "alternate_collector")


class PushConfig(TypedDict):
    batch_name: ReadOnly[str]
    co_slug: ReadOnly[str]
    country_office_id: ReadOnly[int]
    imported_by_email: ReadOnly[str]
    master_detail: ReadOnly[bool]
    pks: ReadOnly[list[int]]
    program_id: ReadOnly[int]
    program_hope_id: ReadOnly[str]
    pushed_by_id: ReadOnly[int]


class WorkflowConfig(PushConfig):
    """Extends PushConfig with the runtime-created RDP id."""

    rdp_id: int


class Route(StrEnum):
    CREATE = auto()
    INDIVIDUALS = auto()
    HOUSEHOLDS = auto()
    PEOPLE = auto()
    COMPLETE = auto()


ROUTES: Final[dict[Route, str]] = {
    Route.CREATE: "{co_slug}/rdi/create/",
    Route.INDIVIDUALS: "{co_slug}/rdi/{rdi_id}/push/lax/individuals/",
    Route.HOUSEHOLDS: "{co_slug}/rdi/{rdi_id}/push/lax/households/",
    Route.PEOPLE: "{co_slug}/rdi/{rdi_id}/push/people/",
    Route.COMPLETE: "{co_slug}/rdi/{rdi_id}/completed/",
}
