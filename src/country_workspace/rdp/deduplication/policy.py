from django.db.models import Q

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES
from country_workspace.rdp.policy import ActionCheck


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
                Q(
                    status__in=(
                        Rdp.PushStatus.SUCCESS,
                        Rdp.PushStatus.REVIEW_PENDING,
                        Rdp.PushStatus.PUSH_PENDING,
                    )
                )
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


def get_program_dedup_settings_policy(program: Program) -> ProgramDedupSettingsPolicy:
    return ProgramDedupSettingsPolicy(program)
