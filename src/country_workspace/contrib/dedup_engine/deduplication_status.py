from enum import StrEnum, auto
from typing import Final, NamedTuple

import sentry_sdk

from country_workspace.exceptions import RemoteUnavailableError
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
    DeduplicationSetState.REJECTED,
)

PROCESSABLE_DEDUPLICATION_SET_STATES: Final[tuple[DeduplicationSetState, ...]] = (
    DeduplicationSetState.READY,
    DeduplicationSetState.ENCODED,
    DeduplicationSetState.ENCODING_FAILED,
    DeduplicationSetState.DEDUPLICATION_FAILED,
)


class DedupResponseStatus(StrEnum):
    OK = auto()
    STATUS_UNAVAILABLE = "N/A"


class DedupClientStatus(NamedTuple):
    response_status: DedupResponseStatus
    deduplication_set_status: str | None
    findings_count: int


def get_deduplication_status(
    program_unicef_id: str,
    deduplication_set_id: str | None,
) -> DedupClientStatus:
    if not deduplication_set_id:
        return DedupClientStatus(
            response_status=DedupResponseStatus.OK,
            deduplication_set_status=None,
            findings_count=-1,
        )

    try:
        with make_client(program_unicef_id, deduplication_set_id=deduplication_set_id) as client:
            payload = client.retrieve_deduplication_set()
    except RemoteUnavailableError as exc:
        sentry_sdk.capture_exception(exc)
        return DedupClientStatus(
            response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
            deduplication_set_status=None,
            findings_count=-1,
        )

    return DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=payload["state"],
        findings_count=payload["findings_count"],
    )
