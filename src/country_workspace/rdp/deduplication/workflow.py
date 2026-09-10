import logging

from typing import Any
from uuid import UUID, uuid4

from constance import config
from django.core import signing
from django.db import transaction
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine import DedupResponseStatus, DeduplicationSetState
from country_workspace.models import AsyncJob, Rdp, RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import create_rdp_core
from country_workspace.rdp.operations import claim_rdp_operation, finish_rdp_operation
from country_workspace.rdp.policy import ActionCheck, get_rdp_policy
from country_workspace.rdp.repository import (
    lock_rdp_for_update,
    qs_individuals_for_rdp,
)
from country_workspace.rdp.push.repository import rdp_for_push
from country_workspace.rdp.push.workflow import push_existing_rdp_core, _fail_pending_push
from country_workspace.rdp.types import RdpWorkflowOutcome

from .constants import DEDUP_CALLBACK_SALT
from .policy import DeduplicationPolicy
from .processor import DedupProcessor
from .repository import (
    release_rdp_dedup_settings_lock,
    rdp_operation_for_dedup,
    rdp_operation_for_dedup_attempt,
)


logger = logging.getLogger(__name__)


def create_rdp_and_start_dedup_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP, upload images to the dedup engine, and start deduplication.

    The dedup engine will call back the notification URL when deduplication finishes.
    The push to HOPE is deferred until the callback is received and the findings
    threshold is evaluated.
    """
    create_result = create_rdp_core(job)
    rdp_id = create_result["rdp_id"]
    check, rdp = claim_rdp_deduplication(rdp_id)
    if rdp is None:
        raise RdpWorkflowError(
            {"errors": [check.reason or "RDP: could not claim deduplication set."], "rdp_id": rdp_id}
        )

    awaiting_callback = False
    try:
        callback_url = _build_dedup_callback_url(rdp_id=rdp_id, job_id=job.pk)
        processor = DedupProcessor(rdp)
        processor.run(notification_url=callback_url)

        if processor.has_errors:
            with transaction.atomic():
                locked = lock_rdp_for_update(pk=rdp_id)
                locked.mark_deduplication_failed()
            raise RdpWorkflowError({**processor.total, "rdp_id": rdp_id})

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp_id)
            locked.mark_deduplication_pending()

        awaiting_callback = True
        return {**create_result, "workflow_outcome": RdpWorkflowOutcome.AWAITING_DEDUP_CALLBACK}
    finally:
        # Keep the lock only while waiting for the HDE callback; release on any failure.
        if not awaiting_callback:
            release_rdp_dedup_settings_lock(rdp_id=rdp_id)


def _build_dedup_callback_url(rdp_id: int, job_id: int) -> str:
    """Build an absolute, signed callback URL for the dedup engine to call when dedup finishes."""
    token = signing.dumps({"rdp_id": rdp_id, "job_id": job_id}, salt=DEDUP_CALLBACK_SALT)
    path = reverse("api:callbacks:dedup-engine-rdp-state-changed", kwargs={"signed_token": token})
    base = config.APP_BASE_URL.rstrip("/")
    return f"{base}{path}"


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, RdpOperation | None]:
    """Claim the deduplication operation for execution."""
    try:
        current = rdp_operation_for_dedup(rdp_id=rdp_id)
    except RdpOperation.DoesNotExist:
        return ActionCheck(False, "RDP: Deduplication is not configured."), None

    policy = DeduplicationPolicy(current.rdp, current)
    if not (check := policy.start_check()).allowed:
        return check, None

    can_create = policy.can_create_deduplication_set

    with transaction.atomic():
        check, operation = claim_rdp_operation(
            rdp_id=rdp_id,
            operation_type=RdpOperation.Type.DEDUPLICATION,
        )
        if operation is None:
            return check, None

        if can_create and not operation.external_id:
            operation.external_id = str(uuid4())
            operation.save(update_fields=["external_id"])

    return check, operation


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the active deduplication attempt."""
    rdp_id = job.config["rdp_id"]
    attempt_id = UUID(job.config["attempt_id"])

    if (operation := rdp_operation_for_dedup_attempt(rdp_id=rdp_id, attempt_id=attempt_id)) is None:
        return {"rdp_id": rdp_id, "skipped": True}

    def run_attempt() -> dict[str, Any]:
        processor = DedupProcessor(operation)
        processor.run()

        if processor.has_errors:
            raise RdpWorkflowError(processor.total)

        return {"rdp_id": rdp_id, "images_sent": processor.total["images_sent"]}

    try:
        return run_attempt()
    except Exception:
        finish_rdp_operation(
            rdp_id=rdp_id,
            operation_type=RdpOperation.Type.DEDUPLICATION,
            attempt_id=attempt_id,
            status=RdpOperation.Status.FAILURE,
        )
        raise


def _lock_and_fail_rdp(rdp_id: int, *, reason: str) -> None:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.status == Rdp.PushStatus.DEDUP_PENDING:
            locked.mark_deduplication_failed()
            logger.warning("dedup_callback_handle: rdp_id=%s marked FAILURE (%s)", rdp_id, reason)
        else:
            logger.info("dedup_callback_handle: rdp_id=%s skip FAILURE (%s); status=%s", rdp_id, reason, locked.status)


def _handle_deduplicated(rdp: Rdp, rdp_id: int, job_id: int, findings_count: int) -> None:
    try:
        origin_job = AsyncJob.objects.get(pk=job_id, rdp_id=rdp_id)
    except AsyncJob.DoesNotExist:
        _lock_and_fail_rdp(rdp_id, reason=f"missing origin AsyncJob id={job_id} for threshold config")
        return

    max_findings_percent: int = origin_job.config.get("max_dedup_findings_percent", 0)

    total_individuals = qs_individuals_for_rdp(rdp=rdp).count()
    if total_individuals == 0:
        _lock_and_fail_rdp(rdp_id, reason="no individuals linked to RDP; cannot compute findings rate")
        return

    findings_rate = findings_count / total_individuals * 100

    logger.info(
        "dedup_callback_handle: rdp_id=%s DEDUPLICATED findings_count=%s total_individuals=%s "
        "findings_rate=%.2f%% max_dedup_findings_percent=%s",
        rdp_id,
        findings_count,
        total_individuals,
        findings_rate,
        max_findings_percent,
    )

    if findings_rate > max_findings_percent:
        _lock_and_fail_rdp(
            rdp_id, reason=f"findings_rate {findings_rate:.2f}% exceeds threshold {max_findings_percent}%"
        )
        return

    try:
        with transaction.atomic():
            locked_rdp = lock_rdp_for_update(pk=rdp_id)
            if locked_rdp.status != Rdp.PushStatus.DEDUP_PENDING:
                logger.warning(
                    "dedup_callback_handle: rdp_id=%s skip push queue; status changed to %s",
                    rdp_id,
                    locked_rdp.status,
                )
                return

            push_attempt_id = locked_rdp.start_push_attempt()
            push_job = AsyncJob.objects.create(
                description=f"Prepare RDP {rdp_id} for HOPE push",
                type=AsyncJob.JobType.TASK,
                owner=locked_rdp.pushed_by,
                action=fqn(push_existing_rdp_core),
                program=locked_rdp.program,
                rdp=locked_rdp,
                config={
                    "rdp_id": rdp_id,
                    "push_attempt_id": str(push_attempt_id),
                    "rdi_id_to_reset": (None if locked_rdp.hope_rdi_id in {None, "N/A"} else locked_rdp.hope_rdi_id),
                },
            )
    except Exception as exc:
        _lock_and_fail_rdp(rdp_id, reason=f"could not create push preparation job: {exc}")
        raise

    try:
        push_job.queue()
    except Exception:
        _fail_pending_push(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
            hope_rdi_id=locked_rdp.hope_rdi_id,
        )
        raise

    logger.info(
        "dedup_callback_handle: rdp_id=%s status DEDUP_PENDING -> PUSH_PENDING; queued preparation job_id=%s",
        rdp_id,
        push_job.pk,
    )


def dedup_callback_handle(rdp_id: int, job_id: int) -> None:
    """Handle a dedup engine callback for the given RDP.

    Fetches the current deduplication set state from the engine.  Only acts on
    terminal states (``DEDUPLICATED``, ``DEDUPLICATION_FAILED``,
    ``ENCODING_FAILED``).  For intermediate states the function returns
    immediately so the engine can call again after the next state transition.

    When dedup is successful and findings are within the configured threshold,
    a ``push_existing_rdp_core`` async job is queued.  Otherwise the RDP is
    marked as ``FAILURE``.
    """
    try:
        rdp = rdp_for_push(pk=rdp_id)
    except Rdp.DoesNotExist:
        logger.warning("dedup_callback_handle: rdp_id=%s not found", rdp_id)
        return

    if rdp.status != Rdp.PushStatus.DEDUP_PENDING:
        logger.info("dedup_callback_handle: rdp_id=%s skip; status=%s (expected DEDUP_PENDING)", rdp_id, rdp.status)
        return

    if not rdp.deduplication_set_id:
        logger.warning("dedup_callback_handle: rdp_id=%s missing deduplication_set_id", rdp_id)
        _lock_and_fail_rdp(rdp_id, reason="missing deduplication_set_id")
        return

    logger.info(
        "dedup_callback_handle: rdp_id=%s job_id=%s deduplication_set_id=%s; fetching remote status",
        rdp_id,
        job_id,
        rdp.deduplication_set_id,
    )

    status = get_rdp_policy(rdp).deduplication_status(rdp)
    if status is None:
        logger.warning(
            "dedup_callback_handle: rdp_id=%s dedup engine returned no status; leaving DEDUP_PENDING", rdp_id
        )
        return

    if status.response_status != DedupResponseStatus.OK:
        logger.warning(
            "dedup_callback_handle: rdp_id=%s dedup engine status unavailable (%s); leaving DEDUP_PENDING",
            rdp_id,
            status.response_status,
        )
        return

    dedup_state = status.deduplication_set_status
    terminal_failure_states = {DeduplicationSetState.DEDUPLICATION_FAILED, DeduplicationSetState.ENCODING_FAILED}

    logger.info(
        "dedup_callback_handle: rdp_id=%s remote_state=%s findings_count=%s",
        rdp_id,
        dedup_state,
        status.findings_count,
    )

    if dedup_state in terminal_failure_states:
        _lock_and_fail_rdp(rdp_id, reason=f"dedup engine state {dedup_state}")
    elif dedup_state == DeduplicationSetState.DEDUPLICATED:
        _handle_deduplicated(rdp, rdp_id, job_id, status.findings_count)
    else:
        logger.info(
            "dedup_callback_handle: rdp_id=%s intermediate state %s; waiting for next callback",
            rdp_id,
            dedup_state,
        )


def create_and_push_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP and start deduplication; the push to HOPE is deferred.

    Push to HOPE is only available for programs with biometric deduplication
    enabled. Deduplication is started first and the push is deferred until the
    dedup engine calls back the notification URL and the findings threshold is
    evaluated.
    """
    rdp_program = job.program
    if not (rdp_program and rdp_program.biometric_deduplication_enabled):
        raise RdpWorkflowError({"errors": ["RDP: push to HOPE requires biometric deduplication for this program."]})
    return create_rdp_and_start_dedup_core(job)
