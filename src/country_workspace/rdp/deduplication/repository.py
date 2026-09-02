from country_workspace.models import Rdp


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def release_rdp_dedup_settings_lock(*, rdp_id: int) -> None:
    """Release the dedup settings lock for an RDP."""
    Rdp.objects.filter(pk=rdp_id, is_dedup_settings_locked=True).update(is_dedup_settings_locked=False)
