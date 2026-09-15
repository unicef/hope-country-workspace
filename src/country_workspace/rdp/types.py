from enum import StrEnum, auto
from typing import NotRequired, ReadOnly, TypedDict


class SelectionConfig(TypedDict):
    pks: ReadOnly[list[int]]
    master_detail: ReadOnly[bool]


class RdpWorkflowOutcome(StrEnum):
    AWAITING_PUSH_READY_CALLBACK = auto()
    DATA_PUSH_QUEUED = auto()
    DATA_PUSH_SKIPPED = auto()


class CreateRdpConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    country_office_id: ReadOnly[int]
    program_id: ReadOnly[int]
    pushed_by_id: ReadOnly[int]


type OperationLogJSONValue = (
    str | int | float | bool | list[OperationLogJSONValue] | dict[str, OperationLogJSONValue] | None
)
type OperationLogResult = dict[str, OperationLogJSONValue]


class OperationLogEntry(TypedDict):
    timestamp: ReadOnly[str]
    action: ReadOnly[str]
    result: NotRequired[OperationLogResult]
