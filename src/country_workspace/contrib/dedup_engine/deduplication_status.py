from enum import StrEnum, auto
from typing import Final, NamedTuple
import sentry_sdk

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from .factory import make_client


class DeduplicationSetState(StrEnum):
    EMPTY = "Empty"
    UPLOADING_IN_PROGRESS = "Uploading in progress"
    READY = "Ready"
    ENCODING_IN_PROGRESS = "Encoding in progress"
    ENCODED = "Encoded"
    ENCODING_FAILED = "Encoding failed"
    DEDUPLICATION_IN_PROGRESS = "Deduplication in progress"
    DEDUPLICATED = "Deduplicated"
    DEDUPLICATION_FAILED = "Deduplication failed"
    APPROVED = "Approved"
    REJECTED = "Rejected"


CLONEABLE_DEDUPLICATION_SET_STATES: Final[tuple[DeduplicationSetState, ...]] = (
    DeduplicationSetState.ENCODING_FAILED,
    DeduplicationSetState.DEDUPLICATION_FAILED,
    DeduplicationSetState.DEDUPLICATED,
    DeduplicationSetState.REJECTED,
)

PROCESSABLE_DEDUPLICATION_SET_STATES: Final[tuple[DeduplicationSetState, ...]] = (DeduplicationSetState.READY,)

PUSHABLE_DEDUPLICATION_SET_STATES: Final[tuple[DeduplicationSetState, ...]] = (DeduplicationSetState.DEDUPLICATED,)

REJECTABLE_DEDUPLICATION_SET_STATES: Final[tuple[DeduplicationSetState, ...]] = (DeduplicationSetState.DEDUPLICATED,)


class DedupResponseStatus(StrEnum):
    OK = auto()
    STATUS_UNAVAILABLE = "N/A"


class DedupClientStatus(NamedTuple):
    response_status: DedupResponseStatus
    deduplication_set_status: str | None
    findings_count: int


def get_deduplication_status(
    group_reference_id: str,
    deduplication_set_id: str | None,
) -> DedupClientStatus:
    if not deduplication_set_id:
        return DedupClientStatus(
            response_status=DedupResponseStatus.OK,
            deduplication_set_status=None,
            findings_count=-1,
        )

    try:
        with make_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
            payload = client.retrieve_deduplication_set()
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        return DedupClientStatus(
            response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
            deduplication_set_status=None,
            findings_count=-1,
        )

    state = payload.get("state")
    findings_count = payload.get("findings_count")

    if not isinstance(state, str) or not isinstance(findings_count, int):
        raise RemoteError(f"DedupEngine: malformed deduplication set status response: {payload}")

    return DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=state,
        findings_count=findings_count,
    )
