from collections.abc import Callable, Iterator
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
from country_workspace.notifications.signals import rdi_push_completed_signal, rdp_push_status_changed_signal
from country_workspace.rdp.deduplication.operations import approve_deduplication_set_after_successful_push
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck, get_rdp_policy
from country_workspace.rdp.push.constants import PUSH_READY_CALLBACK_SALT
from country_workspace.rdp.repository import (
    lock_rdp_for_update,
    qs_households,
    qs_individuals_by_pks,
    qs_individuals_for_push,
    rdp_selection,
    set_rdp_beneficiaries_removed,
)
from country_workspace.rdp.types import RdpWorkflowOutcome

from .processor import PushProcessor
from .repository import (
    claim_rdp_data_push,
    get_or_create_rdp_push_data_job,
    lock_rdp_push_attempt,
    rdp_for_push,
)
from .types import PushAttemptJobConfig, PushPreparationJobConfig, PushWorkflowConfig


def _build_push_ready_callback_url(*, rdp_id: int, push_attempt_id: UUID) -> str:
    """Build the signed HOPE push-ready callback URL."""
    token = signing.dumps(
        {
            "rdp_id": rdp_id,
            "push_attempt_id": str(push_attempt_id),
        },
        salt=PUSH_READY_CALLBACK_SALT,
    )
    path = reverse(
        "api:callbacks:hope-rdp-push-ready",
        kwargs={"signed_token": token},
    )
    return f"{config.APP_BASE_URL.rstrip('/')}{path}"


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


def claim_rdp_push(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Claim an RDP push by starting a new attempt."""
    rdp = rdp_for_push(pk=rdp_id)
    check = get_rdp_policy(rdp).start_push_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if locked.status == Rdp.PushStatus.PUSH_PENDING:
            return ActionCheck(False, "RDP: push to HOPE is already queued or running."), None
        if locked.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not push while deduplication is queued or running."), None
        if locked.status not in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}:
            return ActionCheck(False, f"RDP: can not push in status={locked.status}"), None
        locked.start_push_attempt()

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
            callback_url = _build_push_ready_callback_url(rdp_id=rdp_id, push_attempt_id=push_attempt_id)
            reset_result = HopeApi(co_slug=co_slug).reset_rdi(
                rdi_id=rdi_id_to_reset,
                callback_url=callback_url,
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
