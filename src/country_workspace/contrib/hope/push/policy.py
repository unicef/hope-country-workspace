from dataclasses import dataclass
from functools import cached_property
from typing import NamedTuple

from django.db.models import Q

from country_workspace.contrib.dedup_engine import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    PUSHABLE_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
    make_dedup_client,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError
from country_workspace.models import Program, Rdp

from .repository import has_other_pending_rdp, selection_owner_for_rdp


@dataclass(slots=True, frozen=True)
class ActionCheck:
    allowed: bool
    reason: str | None = None

    def require(self) -> None:
        if not self.allowed:
            raise HopePushError({"errors": [self.reason or "Action is not allowed."]})


class DedupEngineState(NamedTuple):
    status: DedupClientStatus | None = None
    can_create_deduplication_set: bool | None = None

    @classmethod
    def unavailable(cls) -> "DedupEngineState":
        return cls(
            status=DedupClientStatus(
                response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
                deduplication_set_status=None,
                findings_count=-1,
            )
        )

    def __str__(self) -> str:
        result = "-"
        if self.status is None:
            if self.can_create_deduplication_set is not None:
                result = "Ready to start" if self.can_create_deduplication_set else "Can't create deduplication set"
        elif self.status.response_status == DedupResponseStatus.STATUS_UNAVAILABLE:
            result = DedupResponseStatus.STATUS_UNAVAILABLE.value
        elif self.status.response_status != DedupResponseStatus.OK:
            result = "Remote error"
        elif self.status.deduplication_set_status is None:
            result = "Created / waiting for status"
        elif self.status.findings_count >= 0:
            result = f"{self.status.deduplication_set_status} / {self.status.findings_count} findings"
        else:
            result = self.status.deduplication_set_status
        return result


class ProgramDedupSettingsPolicy:
    def __init__(self, program: Program) -> None:
        self.program = program

    def is_update_dedup_settings_visible(self) -> bool:
        return self.program.biometric_deduplication_enabled

    def update_dedup_settings_check(self) -> ActionCheck:
        if not self.program.biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")

        if self._has_locked_dedup_settings():
            return ActionCheck(
                False,
                "Deduplication settings cannot be updated after a successful RDP "
                "or while a pending RDP has requested a new deduplication run.",
            )

        return ActionCheck(True)

    def _has_locked_dedup_settings(self) -> bool:
        return (
            Rdp.objects.filter(program=self.program)
            .filter(Q(status=Rdp.PushStatus.SUCCESS) | Q(status=Rdp.PushStatus.PENDING, is_dedup_settings_locked=True))
            .exists()
        )


class RdpActionPolicy:
    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    @property
    def owner(self) -> Rdp:
        return selection_owner_for_rdp(rdp=self.rdp)

    @property
    def is_pending(self) -> bool:
        return self.rdp.status == self.rdp.PushStatus.PENDING

    @property
    def is_biometric_deduplication_enabled(self) -> bool:
        return self.rdp.program.biometric_deduplication_enabled

    @property
    def has_deduplication_set_id(self) -> bool:
        return bool(self.rdp.deduplication_set_id)

    @property
    def group_reference_id(self) -> str:
        return self.rdp.program.unicef_id

    @staticmethod
    def deduplication_status(rdp: Rdp) -> DedupClientStatus | None:
        if not rdp.deduplication_set_id:
            return None
        return get_deduplication_status(
            group_reference_id=rdp.program.unicef_id,
            deduplication_set_id=str(rdp.deduplication_set_id),
        )

    @cached_property
    def can_create_deduplication_set(self) -> bool:
        with make_dedup_client(self.group_reference_id) as client:
            return client.can_create_deduplication_set()

    @cached_property
    def deduplication_set_state(self) -> str | None:
        if not self.has_deduplication_set_id:
            return None
        with make_dedup_client(
            self.group_reference_id,
            deduplication_set_id=str(self.rdp.deduplication_set_id),
        ) as client:
            return client.retrieve_deduplication_set().get("state")

    def is_deduplicate_visible(self) -> bool:
        return self.is_pending and self.is_biometric_deduplication_enabled

    def is_reject_ds_visible(self) -> bool:
        return self.is_deduplicate_visible() and self.has_deduplication_set_id

    def is_clone_visible(self) -> bool:
        return self.is_biometric_deduplication_enabled

    def is_push_visible(self) -> bool:
        return self.is_pending

    def clone_deduplication_source(self) -> Rdp | None:
        """Return the RDP whose deduplication set should drive clone eligibility."""
        if self.rdp.deduplication_set_id:
            return self.rdp
        if self.owner.deduplication_set_id:
            return self.owner
        return None

    def deduplicate_check(self) -> ActionCheck:
        if not self.is_pending:
            return ActionCheck(False, f"RDP: can not run dedup in status={self.rdp.status}")
        if not self.is_biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")

        if self.can_create_deduplication_set:
            return ActionCheck(True)

        if not self.has_deduplication_set_id:
            return ActionCheck(False, "DedupEngine: can not create deduplication set for this program.")

        if self.deduplication_set_state in PROCESSABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)

        return ActionCheck(
            False,
            f"DedupEngine: can not process deduplication set in state={self.deduplication_set_state!r}.",
        )

    def claim_deduplication_check(self) -> ActionCheck:
        if self.rdp.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP.")
        return self.deduplicate_check()

    def reject_ds_check(self) -> ActionCheck:
        if not self.is_pending:
            return ActionCheck(False, f"RDP: can not reject deduplication set in status={self.rdp.status}")
        if not self.is_biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if not self.has_deduplication_set_id:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")

        if self.deduplication_set_state not in REJECTABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(
                False,
                f"DedupEngine: can not reject deduplication set in state={self.deduplication_set_state!r}.",
            )

        return ActionCheck(True)

    def _clone_deduplication_check(self) -> ActionCheck:
        """Validate deduplication state used for cloning."""
        if (dedup_source := self.clone_deduplication_source()) is None:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")

        status = self.deduplication_status(dedup_source)
        if status is None:
            return ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")
        if status.response_status != DedupResponseStatus.OK:
            return ActionCheck(False, "DedupEngine: can not retrieve deduplication set status.")

        if status.deduplication_set_status not in CLONEABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(
                False,
                f"DedupEngine: can not clone RDP for deduplication set in state={status.deduplication_set_status!r}.",
            )

        return ActionCheck(True)

    def clone_check(self) -> ActionCheck:
        if not self.is_biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if self.rdp.status == Rdp.PushStatus.SUCCESS:
            return ActionCheck(False, "RDP: can not clone a successful RDP.")

        exclude_ids = (self.rdp.pk,) if self.is_pending else ()
        if has_other_pending_rdp(owner=self.owner, exclude_ids=exclude_ids):
            return ActionCheck(False, "RDP: can not clone while another RDP is pending")

        return self._clone_deduplication_check()

    def push_check(self) -> ActionCheck:
        if not self.is_pending:
            return ActionCheck(False, f"RDP: can not push in status={self.rdp.status}")
        if not self.is_biometric_deduplication_enabled or not self.has_deduplication_set_id:
            return ActionCheck(True)

        if self.deduplication_set_state in PUSHABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)

        return ActionCheck(
            False,
            f"DedupEngine: can not push with deduplication set in state={self.deduplication_set_state!r}.",
        )

    def dedup_engine_state(self) -> DedupEngineState:
        if not self.is_pending:
            return DedupEngineState()
        try:
            status = self.deduplication_status(self.rdp)
        except RemoteError:
            if self.can_create_deduplication_set:
                return DedupEngineState(can_create_deduplication_set=True)
            raise
        if status is None:
            return DedupEngineState(can_create_deduplication_set=self.can_create_deduplication_set)
        return DedupEngineState(status=status)


def get_program_dedup_settings_policy(program: Program) -> ProgramDedupSettingsPolicy:
    return ProgramDedupSettingsPolicy(program)


def get_rdp_policy(rdp: Rdp) -> RdpActionPolicy:
    if (policy := getattr(rdp, "_rdp_policy", None)) is None:
        policy = RdpActionPolicy(rdp)
        rdp._rdp_policy = policy
    return policy
