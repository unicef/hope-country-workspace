from typing import TYPE_CHECKING, Any
from contextlib import suppress
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from constance import config
from django.core import signing
from django.db import transaction
from django.urls import reverse

from country_workspace.contrib.dedup_engine import DeduplicationSetState, FindingStatusCode, make_dedup_client
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.repository import (
    append_rdp_operation_log,
    lock_rdp_for_update,
    qs_individuals_for_rdp,
)

from .constants import DEDUP_CALLBACK_SALT
from .processor import DedupProcessor
from .repository import rdp_for_dedup

if TYPE_CHECKING:
    from country_workspace.rdp.types import OperationLogResult


def _build_dedup_callback_url(*, rdp_id: int, deduplication_set_id: UUID) -> str:
    """Build the signed DedupEngine callback URL."""
    token = signing.dumps(
        {
            "rdp_id": rdp_id,
            "deduplication_set_id": str(deduplication_set_id),
        },
        salt=DEDUP_CALLBACK_SALT,
    )
    path = reverse("api:callbacks:dedup-engine-rdp-state-changed", kwargs={"signed_token": token})
    return f"{get_dedup_callback_base_url()}{path}"


def _is_current_deduplication(rdp: Rdp, deduplication_set_id: UUID) -> bool:
    return rdp.status == Rdp.PushStatus.DEDUP_PENDING and rdp.deduplication_set_id == deduplication_set_id


def _require_active_deduplication(rdp: Rdp, deduplication_set_id: UUID) -> None:
    """Require the current deduplication to remain active and locked."""
    if _is_current_deduplication(rdp, deduplication_set_id) and rdp.is_dedup_settings_locked:
        return
    raise RdpWorkflowError(
        {
            "errors": ["RDP: this deduplication job is no longer current."],
            "rdp_id": rdp.pk,
        }
    )


def _require_deduplication_input_count(rdp: Rdp, deduplication_set_id: UUID, images_sent: int) -> int:
    """Resolve the uploaded or recorded deduplication input size."""
    count = images_sent or get_deduplication_input_count(rdp, deduplication_set_id)
    if count is None or count <= 0:
        raise RdpWorkflowError(
            {
                "errors": ["RDP: deduplication input count is not available."],
                "rdp_id": rdp.pk,
            }
        )
    return count


def _fail_current_deduplication(*, rdp_id: int, deduplication_set_id: UUID) -> bool:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if not _is_current_deduplication(locked, deduplication_set_id):
            return False
        locked.fail_deduplication()
    return True


def claim_rdp_deduplication(
    rdp_id: int,
    *,
    can_create_deduplication_set: bool,
    expected_deduplication_set_id: UUID | None,
) -> tuple[ActionCheck, Rdp | None]:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)

        if locked.status not in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not run dedup in status={locked.status}"), None
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP."), None
        if locked.deduplication_set_id != expected_deduplication_set_id:
            return ActionCheck(False, "RDP: deduplication set has changed. Please retry."), None

        if can_create_deduplication_set and locked.deduplication_set_id is None:
            locked.deduplication_set_id = uuid4()
            locked.save(update_fields=["deduplication_set_id"])

        if locked.deduplication_set_id is None:
            return ActionCheck(False, "RDP: deduplication set is not available."), None

        locked.start_deduplication()
        locked.duplicate_individuals.clear()

    return ActionCheck(True), locked


def get_deduplication_input_count(rdp: Rdp, deduplication_set_id: UUID) -> int | None:
    """Return the recorded input size for a DedupEngine set."""
    for entry in reversed(rdp.operation_log or []):
        if entry.get("action") != RdpOperationAction.START_DEDUPLICATION:
            continue

        result = entry.get("result") or {}
        if result.get("deduplication_set_id") != str(deduplication_set_id):
            continue

        count = result.get("dedup_input_count")
        if type(count) is int and count > 0:
            return count

    return None


def get_dedup_callback_base_url() -> str:
    """Return a validated base URL for DedupEngine callbacks."""
    base_url = config.APP_BASE_URL.strip().rstrip("/")

    with suppress(ValueError):
        url = urlsplit(base_url)
        if url.scheme in {"http", "https"} and url.hostname and not (url.query or url.fragment):
            _ = url.port
            return base_url

    raise ValueError("APP_BASE_URL must be a valid absolute HTTP(S) URL.")


def _raise_if_processor_errors(processor: DedupProcessor) -> None:
    """Raise collected deduplication errors."""
    if processor.has_errors:
        raise RdpWorkflowError(processor.total)


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp_id = job.config["rdp_id"]
    deduplication_set_id = UUID(job.config["deduplication_set_id"])
    rdp = rdp_for_dedup(pk=rdp_id)
    _require_active_deduplication(rdp, deduplication_set_id)

    try:
        with make_dedup_client(rdp.program.unicef_id) as client:
            dedup_settings = client.get_deduplication_set_group_config()
    except (RemoteError, RemoteUnavailableError):
        _fail_current_deduplication(rdp_id=rdp_id, deduplication_set_id=deduplication_set_id)
        raise

    processor = DedupProcessor(rdp)

    try:
        processor.prepare(
            notification_url=_build_dedup_callback_url(
                rdp_id=rdp_id,
                deduplication_set_id=deduplication_set_id,
            )
        )
        _raise_if_processor_errors(processor)
        input_count = _require_deduplication_input_count(rdp, deduplication_set_id, processor.total["images_sent"])
        result: OperationLogResult = {
            "images_sent": processor.total["images_sent"],
            "dedup_input_count": input_count,
            "dedup_settings": dedup_settings,
            "deduplication_set_id": str(deduplication_set_id),
        }

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp_id)
            _require_active_deduplication(locked, deduplication_set_id)
            append_rdp_operation_log(
                rdp=locked,
                action=RdpOperationAction.START_DEDUPLICATION,
                result=result,
            )

        with make_dedup_client(
            rdp.program.unicef_id,
            deduplication_set_id=str(deduplication_set_id),
        ) as client:
            if processor.total["images_sent"]:
                processor.run_remote("ready", client.ready)
                _raise_if_processor_errors(processor)
            client.process()

    except RemoteUnavailableError:
        raise
    except Exception:
        _fail_current_deduplication(rdp_id=rdp_id, deduplication_set_id=deduplication_set_id)
        raise

    return {
        "rdp_id": rdp_id,
        "images_sent": processor.total["images_sent"],
        "deduplication_set_id": str(deduplication_set_id),
    }


def sync_deduplication_result(*, rdp_id: int, deduplication_set_id: UUID) -> bool:
    try:
        rdp = rdp_for_dedup(pk=rdp_id)
    except Rdp.DoesNotExist:
        return False

    if not _is_current_deduplication(rdp, deduplication_set_id):
        return False

    with make_dedup_client(
        rdp.program.unicef_id,
        deduplication_set_id=str(deduplication_set_id),
    ) as client:
        deduplication_set = client.retrieve_deduplication_set()
        state = deduplication_set.get("state")
        if not isinstance(state, str):
            raise RemoteError(f"DedupEngine: malformed deduplication set response: {deduplication_set}")

        if state in {
            DeduplicationSetState.ENCODING_FAILED,
            DeduplicationSetState.DEDUPLICATION_FAILED,
        }:
            return _fail_current_deduplication(
                rdp_id=rdp_id,
                deduplication_set_id=deduplication_set_id,
            )

        if state != DeduplicationSetState.DEDUPLICATED:
            return False

        findings_count = deduplication_set.get("findings_count")
        if type(findings_count) is not int or findings_count < 0:
            raise RemoteError(f"DedupEngine: invalid findings_count={findings_count!r}")

        findings = client.retrieve_findings(
            excluded_status_codes={
                FindingStatusCode.FILE_NOT_FOUND,
                FindingStatusCode.GENERIC_ERROR,
            }
        )

    marked_pks = {
        entry["reference_pk"]
        for finding in findings
        for entry in (finding["first"], finding["second"])
        if entry["reference_pk"]
    }
    local_marked_pks = list(qs_individuals_for_rdp(rdp=rdp).filter(pk__in=marked_pks).values_list("pk", flat=True))

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if not _is_current_deduplication(locked, deduplication_set_id):
            return False
        locked.duplicate_individuals.set(local_marked_pks)
        locked.finish_deduplication(findings_count=findings_count)

    return True
