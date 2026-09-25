from contextlib import suppress
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from constance import config
from django.core import signing
from django.urls import reverse

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    SYSTEM_ERROR_STATUS_CODES,
    DeduplicationSetState,
    FindingStatusCode,
    make_dedup_client,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operation import fail_rdp_operation, finish_rdp_operation
from country_workspace.rdp.repository import (
    get_rdp_operation,
    qs_individuals_by_pks,
    qs_individuals_for_rdp,
)

from .constants import DEDUP_CALLBACK_SALT
from .processor import BiometricDedupProcessor


if TYPE_CHECKING:
    from uuid import UUID
    from country_workspace.contrib.dedup_engine.client import Client
    from country_workspace.contrib.dedup_engine.response import Finding
    from country_workspace.rdp.types import JSONValue


def get_dedup_callback_base_url() -> str:
    """Return a validated base URL for DedupEngine callbacks."""
    base_url = config.APP_BASE_URL.strip().rstrip("/")

    with suppress(ValueError):
        url = urlsplit(base_url)
        if url.scheme in {"http", "https"} and url.hostname and not (url.query or url.fragment):
            _ = url.port
            return base_url

    raise ValueError("APP_BASE_URL must be a valid absolute HTTP(S) URL.")


def _finding_status(finding: Finding) -> FindingStatusCode:
    """Return a validated DedupEngine finding status."""
    try:
        return FindingStatusCode(finding["status_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"DedupEngine: invalid finding status: {finding!r}") from exc


def _finding_reference_pk(finding: Finding, entry: Literal["first", "second"]) -> str:
    """Return a validated Individual reference from a DedupEngine finding."""
    try:
        reference_pk = finding[entry]["reference_pk"]
    except (KeyError, TypeError) as exc:
        raise RemoteError(f"DedupEngine: malformed finding entry: {finding!r}") from exc

    if not isinstance(reference_pk, str):
        raise RemoteError(f"DedupEngine: invalid reference_pk={reference_pk!r}")
    return reference_pk


def _finding_individual_id(finding: Finding, entry: Literal["first", "second"]) -> int:
    """Return an Individual ID from a DedupEngine finding."""
    reference_pk = _finding_reference_pk(finding, entry)
    try:
        return int(reference_pk)
    except ValueError as exc:
        raise RemoteError(f"DedupEngine: invalid Individual reference_pk={reference_pk!r}") from exc


def _build_biometric_findings(
    operation: RdpOperation,
    findings: list[Finding],
) -> list[RdpOperationFinding]:
    """Build local biometric findings from a successful DedupEngine result."""
    current_pks = set(qs_individuals_for_rdp(rdp=operation.rdp).values_list("pk", flat=True))
    related_pks: set[int] = set()
    result: list[RdpOperationFinding] = []

    for finding in findings:
        status = _finding_status(finding)
        individual_id = _finding_individual_id(finding, "first")
        if individual_id not in current_pks:
            raise RemoteError(f"DedupEngine: Individual id={individual_id} is not part of the current RDP.")

        related_individual_id = (
            _finding_individual_id(finding, "second") if status == FindingStatusCode.DUPLICATE else None
        )
        if related_individual_id is not None:
            related_pks.add(related_individual_id)

        details = (
            {"score": score}
            if status == FindingStatusCode.DUPLICATE and (score := finding.get("score")) is not None
            else {}
        )
        result.append(
            RdpOperationFinding(
                finding_type=status.name,
                individual_id=individual_id,
                related_individual_id=related_individual_id,
                field_name="photo",
                details=details,
            )
        )

    if missing_pks := related_pks - current_pks:
        existing_pks = set(
            qs_individuals_by_pks(missing_pks)
            .filter(batch__program_id=operation.rdp.program_id)
            .values_list("pk", flat=True)
        )
        if invalid_pks := missing_pks - existing_pks:
            raise RemoteError(f"DedupEngine: invalid related Individual ids={sorted(invalid_pks)}.")

    return result


def _system_error_findings(findings: list[Finding]) -> list[dict[str, JSONValue]]:
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


def _validate_findings_count(*, expected: object, findings: list[Finding]) -> None:
    """Validate the DedupEngine findings count."""
    received = len(findings)
    if type(expected) is not int or expected < 0 or expected != received:
        raise RemoteError(f"DedupEngine: findings_count={expected!r}, received={received}")


def sync_biometric_deduplication_result(*, operation_id: UUID) -> bool:
    """Synchronize a biometric deduplication operation with DedupEngine."""
    try:
        operation = get_rdp_operation(pk=operation_id)
    except RdpOperation.DoesNotExist:
        return False

    if (
        operation.operation_type != RdpOperation.Type.BIOMETRIC_DEDUPLICATION
        or operation.status != RdpOperation.Status.RUNNING
    ):
        return False

    try:
        with make_dedup_client(
            operation.rdp.program.unicef_id,
            deduplication_set_id=str(operation.id),
        ) as client:
            deduplication_set = client.retrieve_deduplication_set()

            if (state := _deduplication_set_state(deduplication_set)) in {
                DeduplicationSetState.ENCODING_FAILED,
                DeduplicationSetState.DEDUPLICATION_FAILED,
            }:
                return fail_rdp_operation(
                    operation_id=operation.id,
                    error={"message": "DedupEngine processing failed.", "state": state.value},
                )

            if state != DeduplicationSetState.DEDUPLICATED:
                return False

            findings = client.retrieve_findings()
            _validate_findings_count(
                expected=deduplication_set.get("findings_count"),
                findings=findings,
            )

        if system_errors := _system_error_findings(findings):
            result = fail_rdp_operation(
                operation_id=operation.id,
                error={
                    "message": "DedupEngine reported system errors.",
                    "count": len(system_errors),
                    "findings": system_errors[:5],
                },
            )
        else:
            result = finish_rdp_operation(
                operation_id=operation.id,
                findings=_build_biometric_findings(operation, findings),
            )

    except RemoteUnavailableError:
        raise
    except RemoteError as exc:
        return fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
    else:
        return result


def _build_dedup_operation_callback_url(*, operation_id: UUID) -> str:
    """Build a signed DedupEngine callback URL for an RDP operation."""
    token = signing.dumps({"operation_id": str(operation_id)}, salt=DEDUP_CALLBACK_SALT)
    path = reverse("api:callbacks:dedup-engine-rdp-state-changed", kwargs={"signed_token": token})
    return f"{get_dedup_callback_base_url()}{path}"


def _get_or_create_biometric_set_state(
    *,
    client: Client,
    operation: RdpOperation,
) -> DeduplicationSetState:
    """Return the existing DedupEngine set state or create the operation set."""
    if (payload := client.retrieve_deduplication_set_or_none()) is not None:
        return _deduplication_set_state(payload)

    if not client.can_create_deduplication_set():
        raise RemoteError("DedupEngine: another deduplication set is active for this program.")

    payload = client.create_deduplication_set(
        notification_url=_build_dedup_operation_callback_url(operation_id=operation.id),
    )
    if payload.get("id") != str(operation.id):
        raise RemoteError(
            f"DedupEngine: deduplication set id mismatch: expected={operation.id}, got={payload.get('id')!r}"
        )

    return _deduplication_set_state(payload)


def _prepare_biometric_set(
    *,
    client: Client,
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
        raise RdpWorkflowError({"errors": ["RDP: no biometric images to deduplicate."]})

    client.ready()
    return DeduplicationSetState.READY


def run_biometric_deduplication(operation: RdpOperation) -> None:
    """Start or resume biometric deduplication for an RDP operation."""
    with make_dedup_client(
        operation.rdp.program.unicef_id,
        deduplication_set_id=str(operation.id),
    ) as client:
        try:
            state = _prepare_biometric_set(client=client, operation=operation)
        except Exception as exc:
            fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
            raise

        if state == DeduplicationSetState.DEDUPLICATED:
            sync_biometric_deduplication_result(operation_id=operation.id)
            return

        if state in {
            DeduplicationSetState.ENCODING_IN_PROGRESS,
            DeduplicationSetState.DEDUPLICATION_IN_PROGRESS,
        }:
            return

        if state not in PROCESSABLE_DEDUPLICATION_SET_STATES:
            message = f"DedupEngine: can not process deduplication set in state={state.value!r}."
            fail_rdp_operation(operation_id=operation.id, error={"message": message})
            raise RdpWorkflowError({"errors": [message]})

        try:
            client.process()
        except RemoteUnavailableError:
            raise
        except Exception as exc:
            fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
            raise
