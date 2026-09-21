from collections.abc import Callable, Iterator
from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID

from constance import config
from django.core import signing
from django.db import transaction
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.contrib.hope.rdi import HopeApi, HopeRdiResetUnconfirmedError, RdiResetResult
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.notifications.signals import rdi_push_completed_signal, rdp_push_status_changed_signal
from country_workspace.rdp.deduplication.operations import approve_deduplication_set_after_successful_push
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.repository import (
    append_rdp_operation_log,
    lock_rdp_for_update,
    qs_households,
    qs_individuals_by_pks,
    qs_individuals_for_push,
    qs_individuals_for_rdp,
    rdp_selection,
    set_rdp_beneficiaries_removed,
)
from country_workspace.rdp.types import OperationLogResult, RdpWorkflowOutcome

from .constants import PUSH_READY_CALLBACK_SALT
from .policy import get_push_policy, threshold_exceeded
from .processor import PushProcessor
from .repository import (
    claim_rdp_data_push,
    get_or_create_rdp_push_data_job,
    lock_rdp_push_attempt,
    rdp_for_push,
)
from .types import PushAttemptJobConfig, PushPreparationJobConfig, PushThresholdType, PushWorkflowConfig


def _build_push_ready_callback_url() -> str:
    """Build the HOPE push-ready callback URL."""
    path = reverse("api:callbacks:hope-rdp-push-ready")
    return f"{config.APP_BASE_URL.rstrip('/')}{path}"


def _build_push_ready_callback_token(*, rdp_id: int, push_attempt_id: UUID) -> str:
    """Build the signed HOPE push-ready callback token."""
    return signing.dumps(
        {"rdp_id": rdp_id, "push_attempt_id": str(push_attempt_id)},
        salt=PUSH_READY_CALLBACK_SALT,
    )


def _workflow_config_for_rdp(*, rdp: Rdp, imported_by_email: str) -> PushWorkflowConfig:
    """Build push workflow config for an existing RDP."""
    master_detail, pks = rdp_selection(rdp=rdp)
    program = rdp.program
    config: PushWorkflowConfig = {
        "batch_name": rdp.name or str(rdp),
        "co_slug": program.country_office.slug,
        "imported_by_email": imported_by_email,
        "master_detail": master_detail,
        "pks": pks,
        "program_hope_id": program.hope_id,
        "rdp_id": rdp.id,
    }
    if program.biometric_deduplication_enabled and rdp.deduplication_set_id:
        config["country_workspace_id"] = str(rdp.deduplication_set_id)
    return config


def _fail_pending_push(*, rdp_id: int, push_attempt_id: UUID, hope_rdi_id: str | None) -> None:
    """Fail the matching active push attempt."""
    with transaction.atomic():
        if (rdp := lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return

        current_rdi_id = rdp.hope_rdi_id if rdp.hope_rdi_id not in {None, "N/A"} else None
        rdp.finish_push_attempt(
            status=Rdp.PushStatus.FAILURE,
            hope_rdi_id=current_rdi_id or hope_rdi_id or "N/A",
        )

        transaction.on_commit(
            partial(
                rdp_push_status_changed_signal.send,
                sender=Rdp,
                program_id=rdp.program_id,
                rdp_id=rdp.pk,
                status=Rdp.PushStatus.FAILURE,
            ),
            robust=True,
        )


def _schedule_push_data(*, rdp_id: int, push_attempt_id: UUID) -> AsyncJob | None:
    """Ensure data push is queued for the active attempt."""
    with transaction.atomic():
        if (rdp := lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return None

        job, created = get_or_create_rdp_push_data_job(
            rdp=rdp,
            push_attempt_id=push_attempt_id,
            action=fqn(push_rdp_data_core),
        )
        if created:
            rdp.hope_rdi_id = None
            rdp.save(update_fields=["hope_rdi_id"])

        if rdp.hope_rdi_id is None:
            transaction.on_commit(job.queue)
            return job

    return None


def check_push_threshold(
    *,
    rdp: Rdp,
    threshold_type: PushThresholdType,
    threshold_value: Decimal,
) -> bool:
    """Check whether marked RDP individuals exceed the selected threshold."""
    return threshold_exceeded(
        marked_count=rdp.duplicate_individuals.count(),
        total_count=qs_individuals_for_rdp(rdp=rdp).count(),
        threshold_type=threshold_type,
        threshold_value=threshold_value,
    )


def _schedule_push_preparation(*, rdp: Rdp, user_id: int) -> None:
    """Create the push preparation job and queue it after commit."""
    if rdp.push_attempt_id is None:
        raise RuntimeError("RDP push attempt was not initialized.")

    job = AsyncJob.objects.create(
        description="Prepare HOPE for RDP push",
        type=AsyncJob.JobType.TASK,
        owner_id=user_id,
        action=fqn(push_existing_rdp_core),
        program_id=rdp.program_id,
        rdp=rdp,
        config={
            "rdp_id": rdp.pk,
            "push_attempt_id": str(rdp.push_attempt_id),
            "rdi_id_to_reset": None if rdp.hope_rdi_id == "N/A" else rdp.hope_rdi_id,
        },
    )
    transaction.on_commit(job.queue)


def _check_locked_push(rdp: Rdp) -> ActionCheck:
    """Check local conditions for starting a push on a locked RDP."""
    if rdp.status == Rdp.PushStatus.PUSH_PENDING:
        return ActionCheck(False, "RDP: push to HOPE is already queued or running.")
    if rdp.is_dedup_settings_locked:
        return ActionCheck(False, "RDP: can not push while deduplication is queued or running.")
    if rdp.status not in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}:
        return ActionCheck(False, f"RDP: can not push in status={rdp.status}")
    return ActionCheck(True)


def claim_rdp_push(
    rdp_id: int,
    *,
    user_id: int,
    threshold: tuple[PushThresholdType, Decimal] | None = None,
) -> tuple[ActionCheck, Rdp | None]:
    """Start an RDP push or place it in review when the threshold is exceeded."""
    rdp = rdp_for_push(pk=rdp_id)
    check = get_push_policy(rdp).start_push_check()
    if not check.allowed:
        return check, None
    if rdp.program.biometric_deduplication_enabled and threshold is None:
        return ActionCheck(False, "RDP: push threshold is required."), None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if not (check := _check_locked_push(locked)).allowed:
            return check, None
        if (
            locked.deduplication_set_id != rdp.deduplication_set_id
            or locked.deduplication_findings_count != rdp.deduplication_findings_count
        ):
            return ActionCheck(False, "RDP: deduplication result has changed. Please retry."), None

        result: OperationLogResult = {"user_id": str(user_id)}
        exceeded = False

        if threshold is not None:
            threshold_type, threshold_value = threshold
            marked_count = locked.duplicate_individuals.count()
            total_count = qs_individuals_for_rdp(rdp=locked).count()
            if total_count == 0:
                return ActionCheck(False, "RDP: no individuals available for push."), None

            exceeded = threshold_exceeded(
                marked_count=marked_count,
                total_count=total_count,
                threshold_type=threshold_type,
                threshold_value=threshold_value,
            )
            result.update(
                threshold_type=threshold_type.value,
                threshold_value=str(threshold_value),
                marked_count=marked_count,
                total_count=total_count,
                marked_percentage=str(Decimal(marked_count) * 100 / total_count),
            )

        if exceeded:
            locked.status = Rdp.PushStatus.REVIEW_PENDING
            locked.save(update_fields=["status"])
        else:
            result["push_attempt_id"] = str(locked.start_push_attempt())

        result["outcome"] = locked.status
        append_rdp_operation_log(rdp=locked, action=RdpOperationAction.PUSH_TO_HOPE, result=result)

        if not exceeded:
            _schedule_push_preparation(rdp=locked, user_id=user_id)

    return ActionCheck(True), locked


def claim_review_rdp_push(rdp_id: int, *, user_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Start a push explicitly approved from review."""
    rdp = rdp_for_push(pk=rdp_id)
    check = get_push_policy(rdp).review_push_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.status != Rdp.PushStatus.REVIEW_PENDING:
            return ActionCheck(False, f"RDP: can not push from review in status={locked.status}"), None
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not push while deduplication is queued or running."), None
        if (
            locked.deduplication_set_id != rdp.deduplication_set_id
            or locked.deduplication_findings_count != rdp.deduplication_findings_count
        ):
            return ActionCheck(False, "RDP: deduplication result has changed. Please retry."), None

        push_attempt_id = locked.start_push_attempt()
        append_rdp_operation_log(
            rdp=locked,
            action=RdpOperationAction.PUSH_TO_HOPE,
            result={
                "user_id": str(user_id),
                "decision": "PUSH",
                "override": True,
                "outcome": Rdp.PushStatus.PUSH_PENDING,
                "push_attempt_id": str(push_attempt_id),
            },
        )
        _schedule_push_preparation(rdp=locked, user_id=user_id)

    return ActionCheck(True), locked


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Prepare HOPE for the RDP push and wait for readiness when required."""
    config: PushPreparationJobConfig = job.config
    rdp_id = config["rdp_id"]
    push_attempt_id = UUID(config["push_attempt_id"])
    rdi_id_to_reset: str | None = None

    def run(rdi_id_to_reset: str | None) -> dict[str, Any]:
        with transaction.atomic():
            rdp = lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)
            if rdp is None:
                raise RdpWorkflowError(
                    {"errors": ["RDP: this push preparation job is no longer current."], "rdp_id": rdp_id}
                )
            co_slug = rdp.program.country_office.slug

        reset_result: RdiResetResult | None = None
        if rdi_id_to_reset is not None:
            reset_result = HopeApi(co_slug=co_slug).reset_rdi(
                rdi_id=rdi_id_to_reset,
                callback_url=_build_push_ready_callback_url(),
                signed_token=_build_push_ready_callback_token(rdp_id=rdp_id, push_attempt_id=push_attempt_id),
            )

            if reset_result == RdiResetResult.ACCEPTED:
                # TODO(Vitali): Use Bitcaster to recover the push attempt if the HOPE reset or callback delivery fails.
                return {
                    "rdp_id": rdp_id,
                    "reset_result": reset_result.value,
                    "workflow_outcome": RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK,
                }

            if reset_result == RdiResetResult.MERGE_IN_PROGRESS:
                raise RdpWorkflowError(
                    {
                        "errors": ["HOPE RDI merge is in progress."],
                        "rdp_id": rdp_id,
                        "hope_rdi_id": rdi_id_to_reset,
                    }
                )

            if reset_result == RdiResetResult.ALREADY_MERGED:
                _finish_already_merged_push(
                    rdp_id=rdp_id,
                    push_attempt_id=push_attempt_id,
                    hope_rdi_id=rdi_id_to_reset,
                )
                return {
                    "rdp_id": rdp_id,
                    "reset_result": reset_result.value,
                    "workflow_outcome": RdpWorkflowOutcome.DATA_PUSH_SKIPPED,
                }

        push_job = _schedule_push_data(rdp_id=rdp_id, push_attempt_id=push_attempt_id)
        return {
            "rdp_id": rdp_id,
            "reset_result": reset_result.value if reset_result else None,
            "workflow_outcome": (
                RdpWorkflowOutcome.DATA_PUSH_QUEUED if push_job else RdpWorkflowOutcome.DATA_PUSH_SKIPPED
            ),
        }

    try:
        rdi_id_to_reset = config["rdi_id_to_reset"]
        return run(rdi_id_to_reset)
    except HopeRdiResetUnconfirmedError:
        # TODO(Vitali): Use Bitcaster to resolve push attempts with an unconfirmed HOPE reset outcome.
        return {
            "rdp_id": rdp_id,
            "reset_result": None,
            "workflow_outcome": RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK,
        }
    except Exception as exc:
        _fail_pending_push(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
            hope_rdi_id=rdi_id_to_reset,
        )
        if isinstance(exc, RdpWorkflowError):
            raise
        raise RdpWorkflowError({"errors": [str(exc)], "rdp_id": rdp_id}) from exc


def handle_push_ready_callback(*, rdp_id: int, push_attempt_id: UUID) -> bool:
    """Schedule data push after HOPE confirms readiness."""
    try:
        return _schedule_push_data(rdp_id=rdp_id, push_attempt_id=push_attempt_id) is not None
    except Exception:
        _fail_pending_push(rdp_id=rdp_id, push_attempt_id=push_attempt_id, hope_rdi_id=None)
        raise


def _push_data_steps(processor: PushProcessor, config: PushWorkflowConfig) -> Iterator[Callable[[], None]]:
    """Yield beneficiary push steps followed by RDI completion."""
    pks = config["pks"]

    if config["master_detail"]:
        yield from (
            partial(processor.run_with, qs_individuals_for_push(pks), processor.rdi_push_individuals),
            partial(processor.run_with, qs_households(pks=pks), processor.rdi_push_households),
        )
    else:
        yield partial(processor.run_with, qs_individuals_by_pks(pks), processor.rdi_push_people)

    yield processor.rdi_complete


def _raise_push_errors(processor: PushProcessor) -> None:
    """Raise collected push errors."""
    if processor.has_errors:
        raise RdpWorkflowError(processor.total)


def _finish_already_merged_push(*, rdp_id: int, push_attempt_id: UUID, hope_rdi_id: str) -> None:
    """Finish the active push when HOPE reports that the existing RDI is already merged."""
    with transaction.atomic():
        if (rdp := lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return

        set_rdp_beneficiaries_removed(rdp=rdp, removed=True)
        rdp.finish_push_attempt(status=Rdp.PushStatus.SUCCESS, hope_rdi_id=hope_rdi_id)
        program_id = rdp.program_id

        transaction.on_commit(
            partial(
                approve_deduplication_set_after_successful_push,
                rdp_id=rdp_id,
                group_reference_id=rdp.program.unicef_id,
                deduplication_set_id=rdp.deduplication_set_id,
            ),
            robust=True,
        )

    rdp_push_status_changed_signal.send_robust(
        sender=Rdp,
        program_id=program_id,
        rdp_id=rdp_id,
        status=Rdp.PushStatus.SUCCESS,
    )


def push_rdp_data_core(job: AsyncJob) -> dict[str, Any]:
    """Create a new RDI and push the RDP data to HOPE."""
    config: PushAttemptJobConfig = job.config
    rdp_id = config["rdp_id"]
    push_attempt_id = UUID(config["push_attempt_id"])
    processor: PushProcessor | None = None

    def run() -> dict[str, Any]:
        nonlocal processor
        if (rdp := claim_rdp_data_push(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return {"rdp_id": rdp_id, "workflow_outcome": RdpWorkflowOutcome.DATA_PUSH_SKIPPED}

        imported_by_email = getattr(job.owner, "email", "") or getattr(rdp.pushed_by, "email", "")
        workflow_config: PushWorkflowConfig = _workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)
        processor = PushProcessor(workflow_config)
        processor.preflight()
        _raise_push_errors(processor)
        processor.rdi_create()
        _raise_push_errors(processor)

        if not (new_rdi_id := processor.hope_rdi_id):
            raise AssertionError("PushProcessor did not set hope_rdi_id")

        with transaction.atomic():
            locked = lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)
            if locked is None:
                raise RdpWorkflowError(
                    {
                        "errors": ["RDP: push attempt changed while creating the new RDI."],
                        "rdp_id": rdp_id,
                    }
                )

            locked.hope_rdi_id = new_rdi_id
            locked.save(update_fields=["hope_rdi_id"])

        for step in _push_data_steps(processor, workflow_config):
            step()
            _raise_push_errors(processor)

        with transaction.atomic():
            locked = lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)
            if locked is None:
                raise RdpWorkflowError({"errors": ["RDP: push attempt changed before completion."], "rdp_id": rdp_id})
            if locked.hope_rdi_id != new_rdi_id:
                raise RuntimeError(
                    f"RDP: hope_rdi_id changed before completion: {locked.hope_rdi_id!r} != {new_rdi_id!r}"
                )

            set_rdp_beneficiaries_removed(rdp=locked, removed=True)
            locked.finish_push_attempt(status=Rdp.PushStatus.SUCCESS, hope_rdi_id=new_rdi_id)
            transaction.on_commit(
                partial(
                    approve_deduplication_set_after_successful_push,
                    rdp_id=rdp_id,
                    group_reference_id=locked.program.unicef_id,
                    deduplication_set_id=locked.deduplication_set_id,
                ),
                robust=True,
            )

        pushed_count = sum(processor.total.get(key, 0) for key in ("households", "individuals", "people"))

        rdi_push_completed_signal.send_robust(sender=Rdp, program_id=rdp.program_id, pushed_count=pushed_count)
        rdp_push_status_changed_signal.send_robust(
            sender=Rdp, program_id=rdp.program_id, rdp_id=rdp.pk, status=Rdp.PushStatus.SUCCESS
        )

        return processor.total

    try:
        return run()
    except Exception:
        _fail_pending_push(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
            hope_rdi_id=processor.hope_rdi_id if processor else None,
        )
        raise


# TODO(Vitali): Remove after Bitcaster recovers stuck RDP push attempts.
def fail_stuck_rdp_push(
    *,
    rdp_id: int,
    push_attempt_id: UUID,
) -> ActionCheck:  # pragma: no cover
    """Temporarily fail a stuck RDP push attempt."""
    with transaction.atomic():
        if (rdp := lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return ActionCheck(False, "RDP: this push attempt is no longer active.")

        jobs = AsyncJob.objects.filter(rdp=rdp, config__push_attempt_id=str(push_attempt_id))

        if not jobs.filter(action=fqn(push_existing_rdp_core)).exists():
            return ActionCheck(False, "RDP: matching push preparation job was not found.")

        if jobs.filter(action=fqn(push_rdp_data_core)).exists():
            return ActionCheck(False, "RDP: data push has already been scheduled.")

        _fail_pending_push(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
            hope_rdi_id=rdp.hope_rdi_id,
        )

    return ActionCheck(True)
