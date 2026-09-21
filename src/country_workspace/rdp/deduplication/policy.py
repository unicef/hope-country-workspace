from functools import cached_property
from typing import NamedTuple

from django.db.models import Q

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    RUNNING_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
    make_dedup_client,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Program, Rdp
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy


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

        try:
            if (
                self._has_blocking_rdp()
                or self._has_running_deduplication_set()
                or self._has_cancelled_set_awaiting_rejection()
            ):
                return ActionCheck(
                    False,
                    "Deduplication settings cannot be updated after a successful RDP "
                    "or while deduplication, review, push to HOPE, or DedupEngine rejection is pending or running.",
                )
        except (RemoteError, RemoteUnavailableError):
            return ActionCheck(False, "DedupEngine: could not verify the current state. Please try again later.")

        return ActionCheck(True)

    def _has_cancelled_set_awaiting_rejection(self) -> bool:
        """Check whether a cancelled RDP still has a rejectable DedupEngine set."""
        rdps = Rdp.objects.filter(
            program=self.program,
            status=Rdp.PushStatus.CANCELLED,
            deduplication_set_id__isnull=False,
        ).select_related("program")
        return any(
            get_deduplication_policy(rdp).deduplication_set_state in REJECTABLE_DEDUPLICATION_SET_STATES for rdp in rdps
        )

    def _has_blocking_rdp(self) -> bool:
        return (
            Rdp.objects.filter(program=self.program)
            .filter(
                Q(status=Rdp.PushStatus.SUCCESS)
                | Q(status__in=NON_TERMINAL_RDP_STATUSES, is_dedup_settings_locked=True)
                | Q(status__in=(Rdp.PushStatus.REVIEW_PENDING, Rdp.PushStatus.PUSH_PENDING))
            )
            .exists()
        )

    def _has_running_deduplication_set(self) -> bool:
        rdp = (
            Rdp.objects.filter(
                program=self.program,
                status__in=NON_TERMINAL_RDP_STATUSES,
                deduplication_set_id__isnull=False,
            )
            .select_related("program")
            .first()
        )
        return bool(rdp and get_deduplication_policy(rdp).deduplication_set_state in RUNNING_DEDUPLICATION_SET_STATES)


class DeduplicationPolicy(RdpActionPolicy):
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
        return self.is_open and self.is_biometric_deduplication_enabled

    def deduplicate_check(self) -> ActionCheck:
        if not self.is_open:
            return ActionCheck(False, f"RDP: can not run dedup in status={self.rdp.status}")
        if not self.is_biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if self.can_create_deduplication_set:
            return ActionCheck(True)
        if not self.has_deduplication_set_id:
            return ActionCheck(False, "DedupEngine: can not create deduplication set for this program.")
        if (state := self.deduplication_set_state) in PROCESSABLE_DEDUPLICATION_SET_STATES:
            return ActionCheck(True)
        return ActionCheck(False, f"DedupEngine: can not process deduplication set in state={state!r}.")

    def claim_deduplication_check(self) -> ActionCheck:
        if self.rdp.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: deduplication has already been started for this RDP.")
        return self.deduplicate_check()

    def cancel_check(self) -> ActionCheck:
        if not (check := super().cancel_check()).allowed:
            return check
        if self.rdp.is_dedup_settings_locked:
            return ActionCheck(False, "RDP: can not cancel while deduplication is queued or running.")
        if not self.is_biometric_deduplication_enabled or not self.has_deduplication_set_id:
            return ActionCheck(True)
        if (state := self.deduplication_set_state) in RUNNING_DEDUPLICATION_SET_STATES:
            return ActionCheck(False, f"DedupEngine: can not cancel RDP with deduplication set in state={state!r}.")
        return ActionCheck(True)

    def dedup_engine_state(self) -> DedupEngineState:
        if self.rdp.status not in NON_TERMINAL_RDP_STATUSES:
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


def get_deduplication_policy(rdp: Rdp) -> DeduplicationPolicy:
    if (policy := getattr(rdp, "_deduplication_policy", None)) is None:
        policy = DeduplicationPolicy(rdp)
        rdp._deduplication_policy = policy
    return policy
