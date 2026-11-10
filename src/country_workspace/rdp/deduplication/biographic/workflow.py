from typing import TYPE_CHECKING, cast

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DATASET_STATES,
    RUNNING_DATASET_STATES,
    BiographicClient,
    BiographicFinding,
    DatasetState,
    FindingScope,
    parse_dataset_state,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.completion import complete_rdp_operation
from country_workspace.rdp.operations.repository import fail_rdp_operation
from country_workspace.rdp.repository import qs_individuals_by_pks, qs_individuals_for_rdp

from ..callbacks import build_dedup_operation_callback_url
from .processor import BiographicDedupProcessor
from .remote import make_operation_client
from .types import BiographicFindingType


if TYPE_CHECKING:
    from country_workspace.rdp.types import JSONValue


NO_RECORDS_ERROR = {"errors": ["RDP: no named individuals to deduplicate."]}


def _individual_id(value: object, label: str) -> int:
    """Return an Individual id from a DedupEngine finding reference."""
    try:
        return int(cast("str", value))
    except (TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: invalid Individual {label}={value!r}") from exc


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
    current_pks = set(qs_individuals_for_rdp(rdp=operation.rdp).values_list("pk", flat=True))
    parsed: list[tuple[BiographicFinding, FindingScope, int, int]] = []

    for finding in findings:
        scope = _finding_scope(finding)
        individual_id = _individual_id(finding.get("reference_pk"), "reference_pk")
        if individual_id not in current_pks:
            raise RemoteError(f"DedupEngine: Individual id={individual_id} is not part of the current RDP.")
        related_id = _individual_id(finding.get("matched_reference_pk"), "matched_reference_pk")
        parsed.append((finding, scope, individual_id, related_id))

    related_pks = {related_id for _, _, _, related_id in parsed}
    local_related_pks = set(
        qs_individuals_by_pks(related_pks)
        .filter(batch__program_id=operation.rdp.program_id)
        .values_list("pk", flat=True)
    )

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


def sync_biographic_result(operation: RdpOperation) -> bool:
    """Synchronize a biographic deduplication operation with DedupEngine."""
    if (
        operation.operation_type != RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION
        or operation.status != RdpOperation.Status.RUNNING
        or not operation.external_id
    ):
        return False

    try:
        with make_operation_client(operation) as client:
            dataset = client.retrieve_dataset()

            if (state := parse_dataset_state(dataset)) == DatasetState.FAILED:
                return fail_rdp_operation(
                    operation_id=operation.id,
                    error={
                        "message": "DedupEngine processing failed.",
                        "state": state.value,
                        "detail": dataset.get("error"),
                    },
                    expected_attempt=operation.attempt,
                )

            if state != DatasetState.DEDUPLICATED:
                return False

            findings = client.retrieve_findings()

        return complete_rdp_operation(
            operation=operation,
            findings=_build_biographic_findings(operation, findings),
        )
    except (RemoteError, RemoteUnavailableError) as exc:
        return fail_rdp_operation(
            operation_id=operation.id,
            error={"message": str(exc)},
            expected_attempt=operation.attempt,
        )


def _get_or_create_dataset_state(*, client: BiographicClient, operation: RdpOperation) -> DatasetState:
    """Return the state of the operation dataset, creating the dataset when it does not exist yet."""
    if operation.external_id and (payload := client.retrieve_dataset_or_none()) is not None:
        return parse_dataset_state(payload)

    if not BiographicDedupProcessor(operation.rdp).has_records():
        raise RdpWorkflowError(NO_RECORDS_ERROR)

    payload = client.create_dataset(notification_url=build_dedup_operation_callback_url(operation_id=operation.id))
    operation.external_id = str(payload["dataset_id"])
    operation.save(update_fields=["external_id"])
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
