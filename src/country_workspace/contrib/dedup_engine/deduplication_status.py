from enum import StrEnum, auto
from typing import NamedTuple

import sentry_sdk

from country_workspace.contrib.dedup_engine.validation import get_optional_int, get_optional_str
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


class DedupResponseStatus(StrEnum):
    OK = auto()
    STATUS_UNAVAILABLE = auto()


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

    deduplication_set_status = get_optional_str(payload, "state")
    return DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=deduplication_set_status,
        findings_count=get_optional_int(payload, "findings_count") if deduplication_set_status is not None else -1,
    )
