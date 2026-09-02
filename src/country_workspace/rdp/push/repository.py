from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from country_workspace.models import AsyncJob, Program, Rdp
from .types import Serializer

if TYPE_CHECKING:
    from .types import PushAttemptJobConfig


def get_or_create_rdp_push_data_job(*, rdp: Rdp, push_attempt_id: UUID, action: str) -> tuple[AsyncJob, bool]:
    """Get or create the data-push job for an already-locked push attempt."""
    config: PushAttemptJobConfig = {"rdp_id": rdp.pk, "push_attempt_id": str(push_attempt_id)}
    return AsyncJob.objects.get_or_create(
        rdp=rdp,
        action=action,
        config=config,
        defaults={
            "description": f"Push RDP {rdp.pk} data to HOPE",
            "type": AsyncJob.JobType.TASK,
            "owner_id": rdp.pushed_by_id,
            "program_id": rdp.program_id,
        },
    )


def claim_rdp_data_push(*, rdp_id: int, push_attempt_id: UUID) -> Rdp | None:
    """Claim data-push execution for the active attempt."""
    with transaction.atomic():
        if (rdp := lock_rdp_push_attempt(rdp_id=rdp_id, push_attempt_id=push_attempt_id)) is None:
            return None
        if rdp.hope_rdi_id is not None:
            return None
        rdp.hope_rdi_id = "N/A"
        rdp.save(update_fields=["hope_rdi_id"])
        return rdp


def lock_rdp_push_attempt(*, rdp_id: int, push_attempt_id: UUID) -> Rdp | None:
    """Lock and return the matching active RDP push attempt."""
    return (
        Rdp.objects.select_for_update()
        .select_related("program")
        .filter(
            pk=rdp_id,
            status=Rdp.PushStatus.PUSH_PENDING,
            push_attempt_id=push_attempt_id,
        )
        .first()
    )


def rdp_for_push(*, pk: int) -> Rdp:
    """Return RDP with relations required for push workflow."""
    return Rdp.objects.select_related(
        "program__country_office",
        "program__beneficiary_group",
        "pushed_by",
    ).get(pk=pk)


def serializer_for_program(hope_id: str) -> Serializer:
    """Return a callable row-serializer for the given Program."""
    prog = Program.objects.select_related("serializer").only("serializer_id").get(hope_id=hope_id)
    return prog.serializer.serialize if prog.serializer else (lambda data: data)
