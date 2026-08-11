from collections.abc import Iterable

from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from country_workspace.models import Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from .types import OperationLogEntry, OperationLogResult


def lock_rdp_for_update(*, pk: int) -> Rdp:
    """Return RDP locked for update."""
    return Rdp.objects.select_for_update().select_related("program").get(pk=pk)


def rdp_selection(*, rdp: Rdp) -> tuple[bool, list[int]]:
    """Return the RDP selection mode and beneficiary IDs."""
    master_detail = rdp.program.beneficiary_group.master_detail
    beneficiaries = rdp.households if master_detail else rdp.individuals
    return master_detail, list(beneficiaries.order_by("pk").values_list("pk", flat=True))


def qs_households(*, pks: Iterable[int]) -> QuerySet[CountryHousehold]:
    """Return Households by ids, ordered by primary key, with prefetched members."""
    return (
        CountryHousehold.objects.filter(pk__in=pks)
        .order_by("id")
        .prefetch_related(
            Prefetch(
                "members",
                queryset=CountryIndividual.objects.only("id").order_by("id"),
                to_attr="prefetched_members",
            )
        )
    )


def qs_individuals_by_household_pks(hh_pks: Iterable[int]) -> QuerySet[CountryIndividual]:
    """Return Individuals filtered by household ids; ordered by primary key."""
    return CountryIndividual.objects.filter(household_id__in=hh_pks).order_by("id")


def qs_individuals_by_pks(pks: Iterable[int]) -> QuerySet[CountryIndividual]:
    """Return Individuals filtered by primary keys; ordered by primary key."""
    return CountryIndividual.objects.filter(pk__in=pks).order_by("id")


def qs_individuals_for_rdp(*, rdp: Rdp) -> QuerySet[CountryIndividual]:
    """Return Individuals selected by the RDP household/individual links."""
    master_detail, pks = rdp_selection(rdp=rdp)
    return qs_individuals_by_household_pks(pks) if master_detail else qs_individuals_by_pks(pks)


def set_rdp_beneficiaries_removed(*, rdp: Rdp, removed: bool) -> None:
    """Set the removed flag for all beneficiaries represented by the RDP."""
    master_detail, pks = rdp_selection(rdp=rdp)
    if master_detail:
        rdp.households.update(removed=removed)
        qs_individuals_by_household_pks(pks).update(removed=removed)
    else:
        rdp.individuals.update(removed=removed)


def set_rdp_push_status(
    *,
    rdp: Rdp,
    status: Rdp.PushStatus,
    hope_rdi_id: str,
    is_dedup_settings_locked: bool | None = None,
) -> None:
    """Persist push status fields for an already-locked RDP."""
    rdp.status = status
    rdp.hope_rdi_id = hope_rdi_id
    update_fields = ["status", "hope_rdi_id"]
    if is_dedup_settings_locked is not None:
        rdp.is_dedup_settings_locked = is_dedup_settings_locked
        update_fields.append("is_dedup_settings_locked")
    rdp.save(update_fields=update_fields)


def append_rdp_operation_log(
    *,
    rdp: Rdp,
    action: RdpOperationAction,
    job_id: int | None = None,
    result: OperationLogResult | None = None,
) -> None:
    """Append an operation log entry to the RDP."""
    entry: OperationLogEntry = {
        "timestamp": timezone.now().isoformat(),
        "action": action.value,
    }
    if job_id is not None:
        entry["job_id"] = job_id
    if result is not None:
        entry["result"] = result

    rdp.operation_log = [*(rdp.operation_log or []), entry]
    rdp.save(update_fields=["operation_log"])
