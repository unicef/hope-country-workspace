from typing import TYPE_CHECKING

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DATASET_STATES,
    RUNNING_DATASET_STATES,
    BiographicClient,
    BiographicFinding,
    DatasetState,
    FindingScope,
    parse_dataset_state,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.exceptions import RdpWorkflowError

from ..findings import local_individual_pks, parse_individual_id, rdp_individual_pks, require_rdp_individual
from ..processing import FetchOutcome, RemoteFailure, get_or_create_remote_set, sync_remote_result
from .processor import BiographicDedupProcessor
from .remote import make_operation_client
from .types import BiographicFindingType


if TYPE_CHECKING:
    from country_workspace.rdp.types import JSONValue


NO_RECORDS_ERROR = {"errors": ["RDP: no named individuals to deduplicate."]}


def _finding_scope(finding: BiographicFinding) -> FindingScope:
    """Return the validated scope of a DedupEngine finding."""
    try:
        return FindingScope(finding["scope"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: invalid finding scope: {finding!r}") from exc


def _build_biographic_findings(
    operation: RdpOperation,
    findings: list[BiographicFinding],
) -> list[RdpOperationFinding]:
    """Build local biographic findings from a successful DedupEngine result."""
    current_pks = rdp_individual_pks(operation)
    parsed: list[tuple[BiographicFinding, FindingScope, int, int]] = []

    for finding in findings:
        scope = _finding_scope(finding)
        individual_id = require_rdp_individual(
            parse_individual_id(finding.get("reference_pk"), "reference_pk"), current_pks
        )
        related_id = parse_individual_id(finding.get("matched_reference_pk"), "matched_reference_pk")
        parsed.append((finding, scope, individual_id, related_id))

    local_related_pks = local_individual_pks(operation, {related_id for _, _, _, related_id in parsed})

    result: list[RdpOperationFinding] = []
    for finding, scope, individual_id, related_id in parsed:
        details: dict[str, JSONValue] = {
            "scope": scope.value,
            "related_reference_pk": related_id,
            "score": finding.get("score"),
            "proximity_to_score": finding.get("proximity_to_score"),
            "matched_full_name": finding.get("matched_full_name"),
            "matched_birth_date": finding.get("matched_birth_date"),
        }
        result.append(
            RdpOperationFinding(
                finding_type=BiographicFindingType.DUPLICATE.value,
                individual_id=individual_id,
                related_individual_id=related_id if related_id in local_related_pks else None,
                details=details,
            )
        )

    return result


def _fetch_biographic_outcome(operation: RdpOperation) -> FetchOutcome:
    """Read the DedupEngine dataset of an operation and return what it means for the operation."""
    with make_operation_client(operation) as client:
        dataset = client.retrieve_dataset()

        if (state := parse_dataset_state(dataset)) == DatasetState.FAILED:
            return RemoteFailure(
                {
                    "message": "DedupEngine processing failed.",
                    "state": state.value,
                    "detail": dataset.get("error"),
                }
            )

        if state != DatasetState.DEDUPLICATED:
            return None

        findings = client.retrieve_findings()

    return _build_biographic_findings(operation, findings)


def sync_biographic_result(operation: RdpOperation) -> bool:
    """Synchronize a biographic deduplication operation with DedupEngine."""
    return sync_remote_result(
        operation,
        operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        fetch=_fetch_biographic_outcome,
    )


def _get_or_create_dataset_state(*, client: BiographicClient, operation: RdpOperation) -> DatasetState:
    """Return the state of the operation dataset, creating the dataset when DedupEngine does not know it yet."""
    payload = get_or_create_remote_set(
        operation,
        label="biographic dataset",
        retrieve=client.retrieve_dataset_or_none,
        create=lambda notification_url: client.create_dataset(notification_url=notification_url),
        remote_id=lambda payload: payload.get("dataset_id"),
        has_input=lambda: BiographicDedupProcessor(operation.rdp).has_records(),
        no_input_error=NO_RECORDS_ERROR,
    )
    return parse_dataset_state(payload)


def _prepare_dataset(*, client: BiographicClient, operation: RdpOperation) -> DatasetState:
    """Create or resume a DedupEngine dataset up to a processable state."""
    state = _get_or_create_dataset_state(client=client, operation=operation)

    # Records are replaced by `reference_pk`, so resuming an interrupted upload is safe.
    if state == DatasetState.PENDING and not BiographicDedupProcessor(operation.rdp).upload_records(client):
        raise RdpWorkflowError(NO_RECORDS_ERROR)

    return state


def run_biographic_deduplication(operation: RdpOperation) -> None:
    """Start or resume biographic deduplication for an RDP operation."""
    with make_operation_client(operation) as client:
        state = _prepare_dataset(client=client, operation=operation)

        if state == DatasetState.DEDUPLICATED:
            sync_biographic_result(operation)
            return

        if state in RUNNING_DATASET_STATES:
            # DedupEngine notifies the callback URL when the run finishes.
            return

        if state not in PROCESSABLE_DATASET_STATES:
            raise RdpWorkflowError(
                {"errors": [f"DedupEngine: can not process biographic dataset in state={state.value!r}."]}
            )

        client.process()
