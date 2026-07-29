import re
from collections.abc import Callable
from enum import StrEnum, auto
from typing import Any, Final, NamedTuple, NotRequired, ReadOnly, TypedDict

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
    max_dedup_findings_percent: NotRequired[int]


class PushWorkflowConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    co_slug: ReadOnly[str]
    imported_by_email: ReadOnly[str]
    program_hope_id: ReadOnly[str]
    rdp_id: ReadOnly[int]
    country_workspace_id: NotRequired[ReadOnly[str]]


class RdpWorkflowOutcome(StrEnum):
    AWAITING_DEDUP_CALLBACK = auto()
    AWAITING_PUSH_READY_CALLBACK = auto()
    DATA_PUSH_QUEUED = auto()
    DATA_PUSH_SKIPPED = auto()


class PushAttemptJobConfig(TypedDict):
    rdp_id: ReadOnly[int]
    push_attempt_id: ReadOnly[str]


class RdiResetResult(StrEnum):
    ACCEPTED = auto()
    NOT_FOUND = auto()
    UNKNOWN = auto()


class Route(StrEnum):
    CREATE_RDI = auto()
    COMPLETE_RDI = auto()
    INDIVIDUALS = auto()
    HOUSEHOLDS = auto()
    PEOPLE = auto()
    RESET_RDI = auto()


ROUTES: Final[dict[Route, str]] = {
    Route.CREATE_RDI: "{co_slug}/rdi/create/",
    Route.COMPLETE_RDI: "{co_slug}/rdi/{rdi_id}/completed/",
    Route.INDIVIDUALS: "{co_slug}/rdi/{rdi_id}/push/lax/individuals/",
    Route.HOUSEHOLDS: "{co_slug}/rdi/{rdi_id}/push/lax/households/",
    Route.PEOPLE: "{co_slug}/rdi/{rdi_id}/push/people/",
    Route.RESET_RDI: "{co_slug}/rdi/{rdi_id}/reset/",
}


class ErrorConfig(NamedTuple):
    MAX_ERRORS: int = 300
    MAX_ERROR_LEN: int = 2000
    MAX_IDS_HINT: int = 5
    MARKER: str = "… further errors truncated …"


ERROR_CONFIG: Final[ErrorConfig] = ErrorConfig()


type OperationLogJSONValue = (
    str | int | float | bool | list[OperationLogJSONValue] | dict[str, OperationLogJSONValue] | None
)
type OperationLogResult = dict[str, OperationLogJSONValue]


class OperationLogEntry(TypedDict):
    timestamp: ReadOnly[str]
    action: ReadOnly[str]
    job_id: NotRequired[int]
    result: NotRequired[OperationLogResult]
