from enum import StrEnum, auto
from typing import NotRequired, ReadOnly, TypedDict


type JSONValue = str | int | float | bool | list[JSONValue] | dict[str, JSONValue] | None
type OperationLogResult = dict[str, JSONValue]


class SelectionConfig(TypedDict):
    pks: ReadOnly[list[int]]
    master_detail: ReadOnly[bool]


class RdpWorkflowOutcome(StrEnum):
    AWAITING_PUSH_READY_CALLBACK = auto()
    DATA_PUSH_QUEUED = auto()
    DATA_PUSH_SKIPPED = auto()


class CreateRdpOperationConfig(TypedDict):
    operation_type: ReadOnly[str]
    config: ReadOnly[dict[str, JSONValue]]


class CreateRdpConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    country_office_id: ReadOnly[int]
    program_id: ReadOnly[int]
    pushed_by_id: ReadOnly[int]
    operations: ReadOnly[list[CreateRdpOperationConfig]]


class OperationLogEntry(TypedDict):
    timestamp: ReadOnly[str]
    action: ReadOnly[str]
    result: NotRequired[OperationLogResult]
