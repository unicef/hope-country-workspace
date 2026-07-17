import logging
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any
from constance import config
from uuid import UUID, uuid4

from django.core import signing
from django.db import IntegrityError, transaction
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.contrib.dedup_engine import (
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DedupResponseStatus,
    DeduplicationSetState,
    make_dedup_client,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp

from .config import CreateRdpConfig, OperationLogResult, PushWorkflowConfig
from .policy import ActionCheck, get_rdp_policy
from .processor import DedupProcessor, PushProcessor
from .repository import (
    append_rdp_operation_log,
    lock_rdp_for_update,
    preflight_errors,
    qs_households,
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    qs_individuals_for_rdp,
    rdp_for_dedup,
    rdp_for_push,
    release_rdp_dedup_settings_lock,
    release_rdp_push_lock,
    set_rdp_push_status,
    workflow_config_for_rdp,
)

DEDUP_CALLBACK_SALT = "dedup_callback"
DEDUP_CALLBACK_MAX_AGE = 60 * 60 * 96  # 96 hours

logger = logging.getLogger(__name__)


def _require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise HopePushError({"errors": ["RDP: beneficiary_group is not set"]})

    config: CreateRdpConfig = job.config
    errors = preflight_errors(
        pks=config["pks"],
        master_detail=config["master_detail"],
        exclude_rdp_ids=(),
    )
    if errors:
        raise HopePushError({"errors": errors})

    if job.program.biometric_deduplication_enabled:
        try:
            with make_dedup_client(job.program.unicef_id) as client:
                if not client.can_create_deduplication_set():
                    raise HopePushError({"errors": ["DedupEngine: can not create deduplication set for this program."]})
        except (RemoteError, RemoteUnavailableError) as e:
            raise HopePushError({"errors": [str(e)]}) from e

    try:
        with transaction.atomic():
            rdp = Rdp.objects.create(
                country_office_id=config["country_office_id"],
                program_id=config["program_id"],
                name=config["batch_name"],
                pushed_by_id=config["pushed_by_id"],
                status=Rdp.PushStatus.PENDING,
            )
            rdp.add_beneficiaries(config["pks"], config["master_detail"])
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)
    except IntegrityError as e:
        message = "RDP: can not create record"
        if "uniq_open_rdp_per_program" in str(e):
            message = "RDP: can not create while another RDP is open"
        raise HopePushError({"errors": [message]}) from e

    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


def _build_dedup_callback_url(rdp_id: int, job_id: int) -> str:
    """Build an absolute, signed callback URL for the dedup engine to call when dedup finishes."""
    token = signing.dumps(
        {"rdp_id": rdp_id, "job_id": job_id},
        salt=DEDUP_CALLBACK_SALT,
    )
    path = reverse("dedup_callback", kwargs={"signed_token": token})
    base = config.APP_BASE_URL.rstrip("/")
    return f"{base}{path}"


def create_rdp_and_start_dedup_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP, upload images to the dedup engine, and start deduplication.

    The dedup engine will call back the notification URL when deduplication finishes.
    The push to HOPE is deferred until the callback is received and the findings
    threshold is evaluated.
    """
    create_result = create_rdp_core(job)
    rdp_id = create_result["rdp_id"]

    with transaction.atomic():
        _check, rdp = claim_rdp_deduplication(rdp_id)
        if rdp is None:
            raise HopePushError({"errors": ["RDP: could not claim deduplication set."], "rdp_id": rdp_id})

    awaiting_callback = False
    try:
        job.refresh_from_db()

        callback_url = _build_dedup_callback_url(rdp_id=rdp_id, job_id=job.pk)
        processor = DedupProcessor(rdp)
        processor.run(notification_url=callback_url)

        if processor.has_errors:
            with transaction.atomic():
                locked = lock_rdp_for_update(pk=rdp_id)
                set_rdp_push_status(
                    rdp=locked,
                    status=Rdp.PushStatus.FAILURE,
                    hope_rdi_id="N/A",
                )
            raise HopePushError({**processor.total, "rdp_id": rdp_id})

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp_id)
            locked.status = Rdp.PushStatus.DEDUP_PENDING
            locked.save(update_fields=["status"])

        awaiting_callback = True
        return {**create_result, "dedup_pending": True}
    finally:
        # Keep the lock only while waiting for the HDE callback; release on any failure.
        if not awaiting_callback:
            release_rdp_dedup_settings_lock(rdp_id=rdp_id)


def create_and_push_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP and start deduplication; the push to HOPE is deferred.

    Push to HOPE is only available for programs with biometric deduplication
    enabled. Deduplication is started first and the push is deferred until the
    dedup engine calls back the notification URL and the findings threshold is
    evaluated.
    """
    rdp_program = job.program
    if not (rdp_program and rdp_program.biometric_deduplication_enabled):
        raise HopePushError({"errors": ["RDP: push to HOPE requires biometric deduplication for this program."]})
    return create_rdp_and_start_dedup_core(job)


def _lock_and_fail_rdp(rdp_id: int, *, reason: str) -> None:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.status == Rdp.PushStatus.DEDUP_PENDING:
            set_rdp_push_status(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")
            logger.warning(
                "dedup_callback_handle: rdp_id=%s marked FAILURE (%s)",
                rdp_id,
                reason,
            )
        else:
            logger.info(
                "dedup_callback_handle: rdp_id=%s skip FAILURE (%s); status=%s",
                rdp_id,
                reason,
                locked.status,
            )


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
            rdp_id,
            reason=f"findings_rate {findings_rate:.2f}% exceeds threshold {max_findings_percent}%",
        )
        return

    with transaction.atomic():
        locked_rdp = lock_rdp_for_update(pk=rdp_id)
        if locked_rdp.status != Rdp.PushStatus.DEDUP_PENDING:
            logger.warning(
                "dedup_callback_handle: rdp_id=%s skip push queue; status changed to %s",
                rdp_id,
                locked_rdp.status,
            )
            return
        locked_rdp.status = Rdp.PushStatus.PENDING
        locked_rdp.save(update_fields=["status"])

        push_job = AsyncJob.objects.create(
            description=f"Push RDP {rdp_id} to HOPE (post-dedup)",
            type=AsyncJob.JobType.TASK,
            owner=locked_rdp.pushed_by,
            action=fqn(push_existing_rdp_core),
            program=locked_rdp.program,
            rdp=locked_rdp,
            config={"rdp_id": rdp_id},
        )
        transaction.on_commit(push_job.queue)

    logger.info(
        "dedup_callback_handle: rdp_id=%s status DEDUP_PENDING→PENDING; queued push job_id=%s",
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
        logger.info(
            "dedup_callback_handle: rdp_id=%s skip; status=%s (expected DEDUP_PENDING)",
            rdp_id,
            rdp.status,
        )
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
            "dedup_callback_handle: rdp_id=%s dedup engine returned no status; leaving DEDUP_PENDING",
            rdp_id,
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


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    rdp = rdp_for_dedup(pk=rdp_id)
    policy = get_rdp_policy(rdp)
    check = policy.deduplicate_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP."), None

        update_fields = ["is_dedup_settings_locked"]
        locked.is_dedup_settings_locked = True
        if policy.can_create_deduplication_set and not locked.deduplication_set_id:
            locked.deduplication_set_id = uuid4()
            update_fields.append("deduplication_set_id")

        locked.save(update_fields=update_fields)

    return ActionCheck(True), locked


def claim_rdp_push(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Claim an RDP push by setting a local push lock."""
    rdp = rdp_for_push(pk=rdp_id)
    check = get_rdp_policy(rdp).start_push_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)

        if locked.is_push_locked:
            return ActionCheck(False, "RDP: push to HOPE is already queued or running."), None
        if locked.status not in {locked.PushStatus.PENDING, locked.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not push in status={locked.status}"), None

        locked.is_push_locked = True
        locked.save(update_fields=["is_push_locked"])

    return ActionCheck(True), locked


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_dedup(pk=rdp_id)

    try:
        _require_policy_check(get_rdp_policy(rdp).deduplicate_check)

        with make_dedup_client(rdp.program.unicef_id) as client:
            dedup_settings = client.get_deduplication_set_group_config()

        processor = DedupProcessor(rdp)
        processor.run()
        result: OperationLogResult = {
            "images_sent": processor.total["images_sent"],
            "dedup_settings": dedup_settings,
            "deduplication_set_id": str(processor.rdp.deduplication_set_id)
            if processor.rdp.deduplication_set_id
            else None,
        }

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp.pk)
            append_rdp_operation_log(
                rdp=locked,
                action=Rdp.OperationAction.START_DEDUPLICATION,
                job_id=job.pk,
                result=result,
            )

        if processor.has_errors:
            raise HopePushError(processor.total)
        return processor.total

    finally:
        release_rdp_dedup_settings_lock(rdp_id=rdp_id)


def cancel_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Cancel an existing RDP and reject its active DedupEngine set when required."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    policy = get_rdp_policy(rdp)
    _require_policy_check(policy.cancel_check)

    group_reference_id = rdp.program.unicef_id
    deduplication_set_id = str(rdp.deduplication_set_id) if rdp.deduplication_set_id else None
    dedup_engine_rejected = False

    if deduplication_set_id and policy.deduplication_set_state in REJECTABLE_DEDUPLICATION_SET_STATES:
        try:
            with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
                client.reject()
        except (RemoteError, RemoteUnavailableError) as e:
            raise HopePushError({"errors": [str(e)]}) from e
        dedup_engine_rejected = True

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.CANCELLED,
            hope_rdi_id=locked.hope_rdi_id or "N/A",
            is_dedup_settings_locked=False,
            is_push_locked=False,
        )

    return {
        "rdp_id": rdp.pk,
        "program": group_reference_id,
        "deduplication_set_id": deduplication_set_id,
        "dedup_engine_rejected": dedup_engine_rejected,
        "cancelled": True,
    }


def _mark_rdp_beneficiaries_removed(rdp: Rdp, is_master_detail: bool) -> None:
    """Mark RDP beneficiaries as removed."""
    if is_master_detail:
        hh_ids = list(rdp.households.values_list("pk", flat=True))
        if not hh_ids:
            return
        rdp.households.update(removed=True)
        qs_individuals_by_household_pks(hh_ids).update(removed=True)
        return
    rdp.individuals.update(removed=True)


def _steps(processor: PushProcessor, config: PushWorkflowConfig) -> Iterator[Callable[[], None]]:
    """Yield the ordered workflow callables; each step appends errors to processor.total."""
    pks = config["pks"]

    yield processor.preflight
    yield processor.rdi_create
    if processor.rdi_already_merged:
        return

    if config["master_detail"]:
        yield from (
            partial(processor.run_with, qs_individuals_by_household_pks(pks), processor.rdi_push_individuals),
            partial(processor.run_with, qs_households(pks=pks), processor.rdi_push_households),
        )
    else:
        yield partial(processor.run_with, qs_individuals_by_pks(pks), processor.rdi_push_people)
    yield processor.rdi_complete


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_push(pk=rdp_id)

    try:
        _require_policy_check(get_rdp_policy(rdp).push_check)
        imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")
        config: PushWorkflowConfig = workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
        hope_processor = PushProcessor(config)

        for step in _steps(hope_processor, config):
            step()
            if hope_processor.has_errors:
                with transaction.atomic():
                    locked = lock_rdp_for_update(pk=rdp.pk)
                    set_rdp_push_status(
                        rdp=locked,
                        status=Rdp.PushStatus.FAILURE,
                        hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
                        is_push_locked=False,
                    )
                raise HopePushError(hope_processor.total)

        with transaction.atomic():
            locked = lock_rdp_for_update(pk=rdp.pk)
            _mark_rdp_beneficiaries_removed(locked, config["master_detail"])
            set_rdp_push_status(
                rdp=locked,
                status=Rdp.PushStatus.SUCCESS,
                hope_rdi_id=hope_processor.hope_rdi_id or "N/A",
                is_push_locked=False,
            )
            group_reference_id = locked.program.unicef_id
            deduplication_set_id = locked.deduplication_set_id

        _approve_deduplication_set_after_successful_push(
            group_reference_id=group_reference_id,
            deduplication_set_id=deduplication_set_id,
            processor=hope_processor,
        )
        return hope_processor.total

    finally:
        release_rdp_push_lock(rdp_id=rdp_id)


def _approve_deduplication_set_after_successful_push(
    group_reference_id: str,
    deduplication_set_id: UUID | None,
    processor: PushProcessor,
) -> None:
    """Approve the active DedupEngine deduplication set after a successful push to HOPE Core."""
    if not deduplication_set_id:
        return

    try:
        with make_dedup_client(
            group_reference_id,
            deduplication_set_id=str(deduplication_set_id),
        ) as client:
            client.approve()
    except (RemoteError, RemoteUnavailableError) as e:
        processor.fail("DedupEngine", f"approve failed. {e}")
