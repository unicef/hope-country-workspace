from collections.abc import Callable, Iterator
from functools import partial
from typing import Any, NamedTuple
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction

from country_workspace.contrib.dedup_engine import (
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
    make_dedup_client,
)
from country_workspace.contrib.hope.exceptions import (
    HopePushError,
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import APIToken, AsyncJob, Rdp

from .config import (
    CreateRdpConfig,
    DEDUP_ENGINE_FINAL_ACTION_BY_RDI_STATUS,
    HopeRdiCallbackCode,
    PushWorkflowConfig,
)
from .policy import ActionCheck, get_rdp_policy
from .processor import DedupProcessor, PushProcessor
from .repository import (
    has_other_pending_rdp,
    lock_rdp_for_update,
    lock_rdp_for_hope_callback,
    preflight_errors,
    preflight_exclude_rdp_ids,
    qs_households,
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    rdp_for_dedup,
    rdp_for_push,
    rdp_selection,
    selection_owner_for_rdp,
    set_rdp_push_status,
    set_rdp_deduplication_snapshot,
    workflow_config_for_rdp,
)


class CloneDeduplicationContext(NamedTuple):
    dedup_source_pk: int
    dedup_source_set_id: UUID
    clone_deduplication_set_id: UUID | None
    snapshot: dict[str, Any]


class HopeRdiCallbackPayload(NamedTuple):
    rdp_id: int | None
    rdi_id: str | None
    status: str | None
    code: HopeRdiCallbackCode
    detail: str

    @classmethod
    def finalized(cls, *, rdp: Rdp, changed: bool) -> "HopeRdiCallbackPayload":
        """Return callback success payload."""
        return cls(
            rdp_id=rdp.pk,
            rdi_id=rdp.hope_rdi_id,
            status=rdp.status,
            code=HopeRdiCallbackCode.FINALIZED if changed else HopeRdiCallbackCode.ALREADY_FINALIZED,
            detail=f"RDP status updated to {rdp.status}." if changed else f"RDP is already {rdp.status}.",
        )

    @classmethod
    def error(
        cls,
        *,
        code: HopeRdiCallbackCode,
        detail: str,
        rdp: Rdp | None = None,
        rdi_id: str | None = None,
    ) -> "HopeRdiCallbackPayload":
        """Return callback error payload."""
        return cls(
            rdp_id=rdp.pk if rdp else None,
            rdi_id=rdp.hope_rdi_id if rdp else rdi_id,
            status=rdp.status if rdp else None,
            code=code,
            detail=detail,
        )

    def as_dict(self) -> dict[str, Any]:
        return self._asdict()


def _require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e


def _deduplication_snapshot(status: DedupClientStatus | None) -> dict[str, Any]:
    """Return a serializable deduplication snapshot from remote status."""
    if status is None:
        return {}
    return {
        "deduplication_set_status": status.deduplication_set_status,
        "findings_count": status.findings_count,
    }


def _save_current_deduplication_snapshot(*, rdp: Rdp, key: str) -> None:
    status = get_rdp_policy(rdp).deduplication_status(rdp)
    snapshot = _deduplication_snapshot(status)
    expected_deduplication_set_id = rdp.deduplication_set_id
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        if locked.deduplication_set_id != expected_deduplication_set_id:
            raise HopePushError({"errors": ["RDP: deduplication state changed. Please retry."]})
        set_rdp_deduplication_snapshot(rdp=locked, key=key, snapshot=snapshot)


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP for the selected beneficiaries after passing preflight checks."""
    if job.program.beneficiary_group is None:
        raise HopePushError({"errors": ["RDP: beneficiary_group is not set"]})
    if not job.config.get("pks"):
        raise HopePushError({"errors": ["RDP: no beneficiaries selected"]})

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
        if "uniq_pending_rdp_per_program" in str(e):
            message = "RDP: can not create while another RDP is pending"
        raise HopePushError({"errors": [message]}) from e

    return {"rdp_id": rdp.id, "rdp_str": str(rdp)}


def claim_rdp_deduplication(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    rdp = lock_rdp_for_update(pk=rdp_id)
    policy = get_rdp_policy(rdp)
    check = policy.claim_deduplication_check()
    if not check.allowed:
        return check, None

    update_fields = ["is_dedup_settings_locked"]
    rdp.is_dedup_settings_locked = True

    if policy.can_create_deduplication_set and not rdp.deduplication_set_id:
        rdp.deduplication_set_id = uuid4()
        update_fields.append("deduplication_set_id")

    rdp.save(update_fields=update_fields)
    return ActionCheck(True), rdp


def dedup_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    _require_policy_check(get_rdp_policy(rdp).deduplicate_check)
    processor = DedupProcessor(rdp)
    processor.run()
    if processor.has_errors:
        raise HopePushError(processor.total)
    return processor.total


def reject_deduplication_set_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Reject the active DedupEngine deduplication set for an existing RDP."""
    rdp = rdp_for_dedup(pk=job.config["rdp_id"])
    _require_policy_check(get_rdp_policy(rdp).reject_ds_check)
    group_reference_id = rdp.program.unicef_id
    deduplication_set_id = str(rdp.deduplication_set_id)
    _save_current_deduplication_snapshot(rdp=rdp, key="before_reject")

    try:
        with make_dedup_client(group_reference_id, deduplication_set_id=deduplication_set_id) as client:
            client.reject()
    except (RemoteError, RemoteUnavailableError) as e:
        raise HopePushError({"errors": [str(e)]}) from e

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.REJECTED,
            hope_rdi_id=locked.hope_rdi_id,
            is_dedup_settings_locked=False,
        )

    return {
        "rdp_id": rdp.pk,
        "program": group_reference_id,
        "deduplication_set_id": deduplication_set_id,
        "rejected": True,
    }


def clone_rdp_core(*, source: Rdp, batch_name: str, pushed_by_id: int) -> Rdp:
    """Create a child RDP from the current RDP deduplication state."""
    _require_policy_check(get_rdp_policy(source).clone_check)

    owner = selection_owner_for_rdp(rdp=source)
    master_detail, pks = rdp_selection(rdp=owner)
    if errors := preflight_errors(
        pks=pks,
        master_detail=master_detail,
        exclude_rdp_ids=preflight_exclude_rdp_ids(rdp=source),
    ):
        raise HopePushError({"errors": errors})

    dedup_source = source if source.deduplication_set_id else owner
    if not dedup_source.deduplication_set_id:
        raise HopePushError({"errors": ["DedupEngine: deduplication_set_id is not set for this RDP."]})
    status = get_rdp_policy(dedup_source).deduplication_status(dedup_source)
    if status is None or status.response_status != DedupResponseStatus.OK:
        raise HopePushError({"errors": ["DedupEngine: can not retrieve deduplication set status."]})

    context = CloneDeduplicationContext(
        dedup_source_pk=dedup_source.pk,
        dedup_source_set_id=dedup_source.deduplication_set_id,
        clone_deduplication_set_id=(
            dedup_source.deduplication_set_id
            if status.deduplication_set_status == DeduplicationSetState.DEDUPLICATED
            else None
        ),
        snapshot=_deduplication_snapshot(status),
    )
    return _clone_rdp_in_transaction(
        source=source,
        batch_name=batch_name,
        pushed_by_id=pushed_by_id,
        context=context,
    )


def _clone_rdp_in_transaction(
    *,
    source: Rdp,
    batch_name: str,
    pushed_by_id: int,
    context: CloneDeduplicationContext,
) -> Rdp:
    try:
        with transaction.atomic():
            source = lock_rdp_for_update(pk=source.pk)
            if source.status == Rdp.PushStatus.MERGED:
                raise HopePushError({"errors": ["RDP: can not clone a merged RDP."]})
            owner = selection_owner_for_rdp(rdp=source)
            if owner.pk != source.pk:
                owner = lock_rdp_for_update(pk=owner.pk)

            exclude_ids = (source.pk,) if source.status == Rdp.PushStatus.PENDING else ()
            if has_other_pending_rdp(owner=owner, exclude_ids=exclude_ids):
                raise HopePushError({"errors": ["RDP: can not clone while another RDP is pending"]})

            current_dedup_source = source if source.deduplication_set_id else owner
            if (
                current_dedup_source.pk != context.dedup_source_pk
                or current_dedup_source.deduplication_set_id != context.dedup_source_set_id
            ):
                raise HopePushError({"errors": ["RDP: deduplication state changed. Please retry."]})

            set_rdp_deduplication_snapshot(rdp=source, key="before_clone", snapshot=context.snapshot)

            update_fields: list[str] = []
            if source.status == Rdp.PushStatus.PENDING:
                source.status = Rdp.PushStatus.REJECTED
                update_fields.append("status")
            if source.is_dedup_settings_locked:
                source.is_dedup_settings_locked = False
                update_fields.append("is_dedup_settings_locked")
            if update_fields:
                source.save(update_fields=update_fields)

            return Rdp.objects.create(
                country_office_id=owner.country_office_id,
                program_id=owner.program_id,
                pushed_by_id=pushed_by_id,
                name=batch_name,
                parent=owner,
                status=Rdp.PushStatus.PENDING,
                deduplication_set_id=context.clone_deduplication_set_id,
                is_dedup_settings_locked=False,
            )
    except IntegrityError as e:
        raise HopePushError({"errors": [f"RDP: can not clone record: {e}"]}) from e


def push_existing_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Run the push workflow for an existing RDP."""
    rdp = rdp_for_push(pk=job.config["rdp_id"])
    _require_policy_check(get_rdp_policy(rdp).push_check)
    _save_current_deduplication_snapshot(rdp=rdp, key="before_push")
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
                    hope_rdi_id=hope_processor.hope_rdi_id,
                )
            raise HopePushError(hope_processor.total)

    if not (hope_rdi_id := hope_processor.hope_rdi_id):
        raise HopePushError({"errors": ["RDI id is not set after successful push."]})

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        _mark_rdp_beneficiaries_removed(locked, config["master_detail"])
        set_rdp_push_status(
            rdp=locked,
            status=Rdp.PushStatus.PUSHED,
            hope_rdi_id=hope_rdi_id,
        )

    return hope_processor.total


def _steps(processor: PushProcessor, config: PushWorkflowConfig) -> Iterator[Callable[[], None]]:
    """Yield the ordered workflow callables; each step appends errors to processor.total."""
    pks = config["pks"]

    yield processor.preflight
    yield processor.rdi_create
    if config["master_detail"]:
        yield from (
            partial(processor.run_with, qs_individuals_by_household_pks(pks), processor.rdi_push_individuals),
            partial(processor.run_with, qs_households(pks=pks), processor.rdi_push_households),
        )
    else:
        yield partial(processor.run_with, qs_individuals_by_pks(pks), processor.rdi_push_people)
    yield processor.rdi_complete


def _mark_rdp_beneficiaries_removed(rdp: Rdp, is_master_detail: bool) -> None:
    """Mark selection-owner beneficiaries as removed."""
    owner = selection_owner_for_rdp(rdp=rdp)
    if is_master_detail:
        hh_ids = list(owner.households.values_list("pk", flat=True))
        if not hh_ids:
            return
        owner.households.update(removed=True)
        qs_individuals_by_household_pks(hh_ids).update(removed=True)
        return
    owner.individuals.update(removed=True)


def apply_hope_rdi_final_status(
    *,
    hope_rdi_id: str,
    status: Rdp.PushStatus,
    token: APIToken,
) -> HopeRdiCallbackPayload:
    """Apply final HOPE Core RDI status to a pushed CW RDP."""
    if not hope_rdi_id:
        raise HopeRdiCallbackError(
            HopeRdiCallbackPayload.error(
                code=HopeRdiCallbackCode.MISSING_RDI_ID,
                detail="RDI id is required.",
            )
        )

    with transaction.atomic():
        try:
            rdp = lock_rdp_for_hope_callback(
                hope_rdi_id=hope_rdi_id,
                token=token,
            )
        except Rdp.DoesNotExist as exc:
            raise HopeRdiCallbackNotFoundError(
                HopeRdiCallbackPayload.error(
                    code=HopeRdiCallbackCode.NOT_FOUND,
                    detail="RDP not found for RDI id.",
                    rdi_id=hope_rdi_id,
                )
            ) from exc

        if rdp.status == status:
            return HopeRdiCallbackPayload.finalized(rdp=rdp, changed=False)

        if rdp.status != Rdp.PushStatus.PUSHED:
            raise HopeRdiCallbackConflictError(
                HopeRdiCallbackPayload.error(
                    code=HopeRdiCallbackCode.INVALID_TRANSITION,
                    detail=f"RDP can not be finalized from status={rdp.status}.",
                    rdp=rdp,
                )
            )

        _finalize_deduplication_set_for_hope_callback(rdp=rdp, status=status)

        if status == Rdp.PushStatus.REJECTED:
            _mark_rdp_beneficiaries_not_removed(rdp)

        set_rdp_push_status(
            rdp=rdp,
            status=status,
            hope_rdi_id=hope_rdi_id,
            is_dedup_settings_locked=False if status == Rdp.PushStatus.REJECTED else None,
        )

        return HopeRdiCallbackPayload.finalized(rdp=rdp, changed=True)


def _finalize_deduplication_set_for_hope_callback(*, rdp: Rdp, status: Rdp.PushStatus) -> None:
    """Apply the final HOPE callback decision to the active DedupEngine set."""
    if not rdp.deduplication_set_id:
        return

    action = DEDUP_ENGINE_FINAL_ACTION_BY_RDI_STATUS[status]
    try:
        with make_dedup_client(
            rdp.program.unicef_id,
            deduplication_set_id=str(rdp.deduplication_set_id),
        ) as client:
            getattr(client, action)()
    except (RemoteError, RemoteUnavailableError) as exc:
        raise HopeRdiCallbackError(
            HopeRdiCallbackPayload.error(
                code=HopeRdiCallbackCode.CALLBACK_ERROR,
                detail=f"DedupEngine: final status sync failed. {exc}",
                rdp=rdp,
            )
        ) from exc


def _mark_rdp_beneficiaries_not_removed(rdp: Rdp) -> None:
    """Mark selection-owner beneficiaries as not removed."""
    owner = selection_owner_for_rdp(rdp=rdp)
    hh_ids = list(owner.households.values_list("pk", flat=True))
    if hh_ids:
        owner.households.update(removed=False)
        qs_individuals_by_household_pks(hh_ids).update(removed=False)
        return
    owner.individuals.update(removed=False)
