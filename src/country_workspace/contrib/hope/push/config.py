import re
from collections.abc import Callable
from typing import Any, TypedDict, ReadOnly, Final, NamedTuple
from enum import StrEnum, auto

from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


type Beneficiary = CountryHousehold | CountryIndividual
type Serializer = Callable[[list[dict]], Any]

# Matches tags like: IND-25-0000.0051
IND_TAG_RE = re.compile(r"^IND(?:-\d+)+\.\d+$")


class SelectionConfig(TypedDict):
    pks: ReadOnly[list[int]]
    master_detail: ReadOnly[bool]


class CreateRdpConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    country_office_id: ReadOnly[int]
    program_id: ReadOnly[int]
    pushed_by_id: ReadOnly[int]


class PushExistingRdpConfig(TypedDict):
    rdp_id: ReadOnly[int]


class PushWorkflowConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    co_slug: ReadOnly[str]
    imported_by_email: ReadOnly[str]
    program_hope_id: ReadOnly[str]
    rdp_id: ReadOnly[int]


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


class ErrorConfig(NamedTuple):
    MAX_ERRORS: int = 300
    MAX_ERROR_LEN: int = 2000
    MAX_IDS_HINT: int = 5
    MARKER: str = "… further errors truncated …"


ERROR_CONFIG: Final[ErrorConfig] = ErrorConfig()
