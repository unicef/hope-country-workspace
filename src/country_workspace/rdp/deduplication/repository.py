from uuid import UUID

from country_workspace.models import Rdp, RdpOperation


def rdp_operation_for_dedup(*, rdp_id: int) -> RdpOperation:
    """Return the deduplication operation with its RDP and Program loaded."""
    return RdpOperation.objects.select_related("rdp__program").get(rdp_id=rdp_id, type=RdpOperation.Type.DEDUPLICATION)


def rdp_operation_for_dedup_attempt(*, rdp_id: int, attempt_id: UUID) -> RdpOperation | None:
    """Return the matching active deduplication attempt."""
    operation = rdp_operation_for_dedup(rdp_id=rdp_id)
    if operation.status != RdpOperation.Status.IN_PROGRESS or operation.attempt_id != attempt_id:
        return None
    return operation


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def release_rdp_dedup_settings_lock(*, rdp_id: int) -> None:
    """Release the dedup settings lock for an RDP."""
    Rdp.objects.filter(pk=rdp_id, is_dedup_settings_locked=True).update(is_dedup_settings_locked=False)
