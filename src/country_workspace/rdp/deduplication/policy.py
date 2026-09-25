from functools import cached_property
from typing import NamedTuple

from django.db.models import Q

from country_workspace.contrib.dedup_engine import (
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
    make_dedup_client,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Program, Rdp, RdpOperation
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
            blocked = self._has_blocking_rdp() or self._has_blocking_deduplication_set()
        except (RemoteError, RemoteUnavailableError):
            return ActionCheck(False, "DedupEngine: could not verify the current state. Please try again later.")

        if blocked:
            return ActionCheck(
                False,
                "Deduplication settings cannot be updated after a successful RDP "
                "or while deduplication, review, push to HOPE, or DedupEngine rejection is pending or running.",
            )

        return ActionCheck(True)

    def _has_blocking_rdp(self) -> bool:
        return (
            Rdp.objects.filter(program=self.program)
            .filter(
                Q(status=Rdp.PushStatus.SUCCESS)
                | Q(status__in=NON_TERMINAL_RDP_STATUSES, is_dedup_settings_locked=True)
                | Q(status__in=(Rdp.PushStatus.REVIEW_PENDING, Rdp.PushStatus.PUSH_PENDING))
                | Q(
                    status__in=NON_TERMINAL_RDP_STATUSES,
                    operations__operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
                )
            )
            .exists()
        )

    def _has_blocking_deduplication_set(self) -> bool:
        """Check whether DedupEngine has a set blocking further changes."""
        with make_dedup_client(self.program.unicef_id) as client:
            return not client.can_create_deduplication_set()


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
