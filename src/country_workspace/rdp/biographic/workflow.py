from uuid import UUID

from django.core import signing
from django.urls import reverse

from country_workspace.contrib.biographic_dedup import (
    PROCESSABLE_BIOGRAPHIC_SET_STATES,
    RUNNING_BIOGRAPHIC_SET_STATES,
    BiographicSetState,
    FindingScope,
    make_biographic_client,
    parse_set_state,
)
from country_workspace.contrib.biographic_dedup.client import BiographicClient
from country_workspace.contrib.biographic_dedup.schemas import BiographicFinding
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.deduplication.constants import DEDUP_CALLBACK_SALT
from country_workspace.rdp.deduplication.workflow import get_dedup_callback_base_url
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.completion import complete_rdp_operation
from country_workspace.rdp.operations.repository import fail_rdp_operation, get_rdp_operation
from country_workspace.rdp.repository import qs_individuals_by_pks, qs_individuals_for_rdp

from .constants import BIOGRAPHIC_DUPLICATE_FINDING_TYPE
from .processor import BiographicDedupProcessor


def _build_callback_url(*, operation_id: UUID) -> str:
    """Build the signed URL DedupEngine pings on every state change of the set."""
    token = signing.dumps({"operation_id": str(operation_id)}, salt=DEDUP_CALLBACK_SALT)
    path = reverse("api:callbacks:dedup-engine-rdp-state-changed", kwargs={"signed_token": token})
    return f"{get_dedup_callback_base_url()}{path}"


def _individual_id(value: object, label: str) -> int:
    """Return an Individual id from a DedupEngine finding reference."""
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError) as exc:
        raise RemoteError(f"Biographic DedupEngine: invalid Individual {label}={value!r}") from exc


def _finding_scope(finding: BiographicFinding) -> FindingScope:
    """Return the validated scope of a DedupEngine finding."""
    try:
        return FindingScope(finding["scope"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"Biographic DedupEngine: invalid finding scope: {finding!r}") from exc


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
            raise RemoteError(f"Biographic DedupEngine: Individual id={individual_id} is not part of the current RDP.")
        related_id = _individual_id(finding.get("matched_reference_pk"), "matched_reference_pk")
        parsed.append((finding, scope, individual_id, related_id))

    related_pks = {related_id for _, _, _, related_id in parsed}
    local_related_pks = set(
        qs_individuals_by_pks(related_pks)
        .filter(batch__program_id=operation.rdp.program_id)
        .values_list("pk", flat=True)
    )

    return [
        RdpOperationFinding(
            finding_type=BIOGRAPHIC_DUPLICATE_FINDING_TYPE,
            individual_id=individual_id,
            related_individual_id=related_id if related_id in local_related_pks else None,
            details={
                "scope": scope.value,
                "score": finding.get("score"),
                "proximity_to_score": finding.get("proximity_to_score"),
                "matched_full_name": finding.get("matched_full_name"),
                "matched_birth_date": finding.get("matched_birth_date"),
            },
        )
        for finding, scope, individual_id, related_id in parsed
    ]


def sync_biographic_deduplication_result(*, operation_id: UUID) -> bool:
    """Synchronize a biographic deduplication operation with DedupEngine."""
    try:
        operation = get_rdp_operation(pk=operation_id)
    except RdpOperation.DoesNotExist:
        return False

    if (
        operation.operation_type != RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION
        or operation.status != RdpOperation.Status.RUNNING
        or not operation.external_id
    ):
        return False

    try:
        with make_biographic_client(operation.rdp.program, dataset_id=operation.external_id) as client:
            dataset = client.retrieve_dataset()

            if (state := parse_set_state(dataset)) == BiographicSetState.FAILED:
                return fail_rdp_operation(
                    operation_id=operation.id,
                    error={
                        "message": "Biographic DedupEngine processing failed.",
                        "state": state.value,
                        "detail": dataset.get("error"),
                    },
                )

            if state != BiographicSetState.DEDUPLICATED:
                return False

            findings = client.retrieve_findings()

        return complete_rdp_operation(
            operation=operation,
            findings=_build_biographic_findings(operation, findings),
        )
    except (RemoteError, RemoteUnavailableError) as exc:
        return fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})


def _get_or_create_set_state(*, client: BiographicClient, operation: RdpOperation) -> BiographicSetState:
    """Return the state of the operation's set, creating the set when it does not exist yet."""
    if operation.external_id and (payload := client.retrieve_dataset_or_none()) is not None:
        return parse_set_state(payload)

    if not BiographicDedupProcessor(operation.rdp).has_records():
        raise RdpWorkflowError({"errors": ["RDP: no named individuals to deduplicate."]})

    payload = client.create_dataset(notification_url=_build_callback_url(operation_id=operation.id))
    operation.external_id = str(payload["dataset_id"])
    operation.save(update_fields=["external_id"])
    return parse_set_state(payload)


def _prepare_set(*, client: BiographicClient, operation: RdpOperation) -> BiographicSetState:
    """Create or resume a DedupEngine set up to a processable state."""
    state = _get_or_create_set_state(client=client, operation=operation)

    # Records are replaced by `reference_pk`, so resuming an interrupted upload is safe.
    if state == BiographicSetState.PENDING and not BiographicDedupProcessor(operation.rdp).upload_records(client):
        raise RdpWorkflowError({"errors": ["RDP: no named individuals to deduplicate."]})

    return state


def run_biographic_deduplication(operation: RdpOperation) -> None:
    """Start or resume biographic deduplication for an RDP operation."""
    with make_biographic_client(
        operation.rdp.program,
        dataset_id=operation.external_id or None,
    ) as client:
        state = _prepare_set(client=client, operation=operation)

        if state == BiographicSetState.DEDUPLICATED:
            sync_biographic_deduplication_result(operation_id=operation.id)
            return

        if state in RUNNING_BIOGRAPHIC_SET_STATES:
            # DedupEngine notifies the callback URL when the run finishes.
            return

        if state not in PROCESSABLE_BIOGRAPHIC_SET_STATES:
            raise RdpWorkflowError(
                {"errors": [f"Biographic DedupEngine: can not process set in state={state.value!r}."]}
            )

        client.process()
