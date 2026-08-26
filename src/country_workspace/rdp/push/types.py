from collections.abc import Callable
from typing import Any, NotRequired, ReadOnly, TypedDict

from country_workspace.rdp.types import SelectionConfig

type Serializer = Callable[[list[dict]], Any]


class PushWorkflowConfig(SelectionConfig):
    batch_name: ReadOnly[str]
    co_slug: ReadOnly[str]
    imported_by_email: ReadOnly[str]
    program_hope_id: ReadOnly[str]
    rdp_id: ReadOnly[int]
    country_workspace_id: NotRequired[ReadOnly[str]]


class PushAttemptJobConfig(TypedDict):
    rdp_id: ReadOnly[int]
    push_attempt_id: ReadOnly[str]


class PushPreparationJobConfig(PushAttemptJobConfig):
    rdi_id_to_reset: ReadOnly[str | None]
