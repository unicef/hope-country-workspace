from typing import Any, Literal

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    SYSTEM_ERROR_STATUS_CODES,
    BiometricClient,
    BiometricFinding,
    DeduplicationSetState,
    FindingStatusCode,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.types import JSONValue

from ..findings import local_individual_pks, parse_individual_id, require_rdp_individual, rdp_individual_pks
from ..processing import FetchOutcome, RemoteFailure, get_or_create_remote_set, sync_remote_result
from .processor import BiometricDedupProcessor
from .remote import make_operation_client

NO_IMAGES_ERROR = {"errors": ["RDP: no biometric images to deduplicate."]}


def _finding_status(finding: BiometricFinding) -> FindingStatusCode:
    """Return a validated DedupEngine finding status."""
    try:
        return FindingStatusCode(finding["status_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: invalid finding status: {finding!r}") from exc


def _finding_reference_pk(finding: BiometricFinding, entry: Literal["first", "second"]) -> str:
    """Return a validated Individual reference from a DedupEngine finding."""
    try:
        reference_pk = finding[entry]["reference_pk"]
    except (KeyError, TypeError) as exc:
        raise RemoteError(f"DedupEngine: malformed finding entry: {finding!r}") from exc

    if not isinstance(reference_pk, str):
        raise RemoteError(f"DedupEngine: invalid reference_pk={reference_pk!r}")
    return reference_pk


def _finding_individual_id(finding: BiometricFinding, entry: Literal["first", "second"]) -> int:
    """Return an Individual ID from a DedupEngine finding."""
    return parse_individual_id(_finding_reference_pk(finding, entry), "reference_pk")


def _build_biometric_findings(
    operation: RdpOperation,
    findings: list[BiometricFinding],
) -> list[RdpOperationFinding]:
    """Build local biometric findings from a successful DedupEngine result."""
    current_pks = rdp_individual_pks(operation)
    parsed: list[tuple[BiometricFinding, FindingStatusCode, int, int | None]] = []

    for finding in findings:
        status = _finding_status(finding)
        individual_id = require_rdp_individual(_finding_individual_id(finding, "first"), current_pks)

        related_id = _finding_individual_id(finding, "second") if status == FindingStatusCode.DUPLICATE else None
        parsed.append((finding, status, individual_id, related_id))

    local_related_pks = local_individual_pks(
        operation, {related_id for _, _, _, related_id in parsed if related_id is not None}
    )

    result: list[RdpOperationFinding] = []
    for finding, status, individual_id, related_id in parsed:
        details: dict[str, JSONValue] = {}
        if status == FindingStatusCode.DUPLICATE:
            details["related_reference_pk"] = related_id
            if (score := finding.get("score")) is not None:
                details["score"] = score

        result.append(
            RdpOperationFinding(
                finding_type=status.name,
                individual_id=individual_id,
                related_individual_id=related_id if related_id in local_related_pks else None,
                field_name="photo",
                details=details,
            )
        )

    return result


def _system_error_findings(findings: list[BiometricFinding]) -> list[dict[str, JSONValue]]:
    """Return DedupEngine system errors from findings."""
    return [
        {
            "status": status.name,
            "reference_pk": _finding_reference_pk(finding, "first"),
        }
        for finding in findings
        if (status := _finding_status(finding)) in SYSTEM_ERROR_STATUS_CODES
    ]


def _deduplication_set_state(payload: dict[str, Any]) -> DeduplicationSetState:
    """Return a validated DedupEngine set state."""
    try:
        return DeduplicationSetState(payload["state"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: malformed deduplication set response: {payload}") from exc


def _validate_findings_count(*, expected: object, findings: list[BiometricFinding]) -> None:
    """Validate the DedupEngine findings count."""
    received = len(findings)
    if type(expected) is not int or expected < 0 or expected != received:
        raise RemoteError(f"DedupEngine: findings_count={expected!r}, received={received}")


def _fetch_biometric_outcome(operation: RdpOperation) -> FetchOutcome:
    """Read the DedupEngine set of an operation and return what it means for the operation."""
    with make_operation_client(operation) as client:
        deduplication_set = client.retrieve_deduplication_set()

        if (state := _deduplication_set_state(deduplication_set)) in {
            DeduplicationSetState.ENCODING_FAILED,
            DeduplicationSetState.DEDUPLICATION_FAILED,
        }:
            return RemoteFailure({"message": "DedupEngine processing failed.", "state": state.value})

        if state != DeduplicationSetState.DEDUPLICATED:
            return None

        findings = client.retrieve_findings()
        _validate_findings_count(
            expected=deduplication_set.get("findings_count"),
            findings=findings,
        )

    if system_errors := _system_error_findings(findings):
        return RemoteFailure(
            {
                "message": "DedupEngine reported system errors.",
                "count": len(system_errors),
                "findings": system_errors[:5],
            }
        )

    return _build_biometric_findings(operation, findings)


def sync_biometric_result(operation: RdpOperation) -> bool:
    """Synchronize a biometric deduplication operation with DedupEngine."""
    return sync_remote_result(
        operation,
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        fetch=_fetch_biometric_outcome,
    )


def _get_or_create_biometric_set_state(
    *,
    client: BiometricClient,
    operation: RdpOperation,
) -> DeduplicationSetState:
    """Return the existing DedupEngine set state or create the operation set."""

    def ensure_can_create() -> None:
        if not client.can_create_deduplication_set():
            raise RemoteError("DedupEngine: another deduplication set is active for this program.")

    payload = get_or_create_remote_set(
        operation,
        label="deduplication set",
        retrieve=client.retrieve_deduplication_set_or_none,
        create=lambda notification_url: client.create_deduplication_set(notification_url=notification_url),
        remote_id=lambda payload: payload.get("id"),
        has_input=lambda: BiometricDedupProcessor(operation.rdp).has_images(),
        no_input_error=NO_IMAGES_ERROR,
        before_create=ensure_can_create,
    )
    return _deduplication_set_state(payload)


def _prepare_biometric_set(
    *,
    client: BiometricClient,
    operation: RdpOperation,
) -> DeduplicationSetState:
    """Create or resume a DedupEngine set up to a processable state."""
    state = _get_or_create_biometric_set_state(client=client, operation=operation)

    if state not in {
        DeduplicationSetState.EMPTY,
        DeduplicationSetState.UPLOADING_IN_PROGRESS,
    }:
        return state

    if not BiometricDedupProcessor(operation.rdp).upload_images(client):
        raise RdpWorkflowError(NO_IMAGES_ERROR)

    client.ready()
    return DeduplicationSetState.READY


def run_biometric_deduplication(operation: RdpOperation) -> None:
    """Start or resume biometric deduplication for an RDP operation."""
    with make_operation_client(operation) as client:
        state = _prepare_biometric_set(client=client, operation=operation)

        if state == DeduplicationSetState.DEDUPLICATED:
            sync_biometric_result(operation)
            return

        if state in {
            DeduplicationSetState.ENCODING_IN_PROGRESS,
            DeduplicationSetState.DEDUPLICATION_IN_PROGRESS,
        }:
            return

        if state not in PROCESSABLE_DEDUPLICATION_SET_STATES:
            raise RdpWorkflowError(
                {"errors": [f"DedupEngine: can not process deduplication set in state={state.value!r}."]}
            )

        # TODO(Vitali): Use Bitcaster to recover RUNNING operations when DedupEngine callback delivery fails.
        client.process()
