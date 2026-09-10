from django.db.models import Q

from country_workspace.contrib.dedup_engine import RUNNING_DEDUPLICATION_SET_STATES
from country_workspace.models import Program, Rdp
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES

from .common import ActionCheck
from .rdp import RdpActionPolicy


class ProgramDedupSettingsPolicy:
    def __init__(self, program: Program) -> None:
        self.program = program

    def is_update_dedup_settings_visible(self) -> bool:
        return self.program.biometric_deduplication_enabled

    def update_dedup_settings_check(self) -> ActionCheck:
        if not self.program.biometric_deduplication_enabled:
            return ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program.")
        if self._has_blocking_rdp() or self._has_running_deduplication_set():
            return ActionCheck(
                False,
                "Deduplication settings cannot be updated after a successful RDP "
                "or while deduplication or push to HOPE is queued or running.",
            )
        return ActionCheck(True)

    def _has_blocking_rdp(self) -> bool:
        return (
            Rdp.objects.filter(program=self.program)
            .filter(
                Q(status=Rdp.PushStatus.SUCCESS)
                | Q(status__in=NON_TERMINAL_RDP_STATUSES, is_dedup_settings_locked=True)
                | Q(status=Rdp.PushStatus.PUSH_PENDING)
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
        return bool(rdp and RdpActionPolicy(rdp).deduplication_set_state in RUNNING_DEDUPLICATION_SET_STATES)


def get_program_dedup_settings_policy(program: Program) -> ProgramDedupSettingsPolicy:
    return ProgramDedupSettingsPolicy(program)
