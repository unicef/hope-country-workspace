from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.db.models import Prefetch, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.models import Rdp
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from .types import CreateRdpConfig, OperationLogResult

if TYPE_CHECKING:
    from .types import OperationLogEntry


def lock_rdp_for_update(*, pk: int) -> Rdp:
    """Return RDP locked for update."""
    return Rdp.objects.select_for_update().select_related("program").get(pk=pk)


def rdp_selection(*, rdp: Rdp) -> tuple[bool, list[int]]:
    """Return the RDP selection mode and beneficiary IDs."""
    master_detail = rdp.program.beneficiary_group.master_detail
    beneficiaries = rdp.households if master_detail else rdp.individuals
    return master_detail, list(beneficiaries.order_by("pk").values_list("pk", flat=True))


def create_rdp(*, config: CreateRdpConfig) -> Rdp:
    """Create an RDP with its beneficiaries and configured operations."""
    rdp = Rdp.objects.create(
        country_office_id=config["country_office_id"],
        program_id=config["program_id"],
        name=config["batch_name"],
        pushed_by_id=config["pushed_by_id"],
        status=Rdp.PushStatus.PENDING,
    )
    rdp.add_beneficiaries(config["pks"], config["master_detail"])
    for operation in config["operations"]:
        rdp.operations.create(operation_type=operation["operation_type"], config=operation["config"])
    return rdp


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


def count_rdp_individuals(*, pks: Iterable[int], master_detail: bool) -> int:
    """Return the number of individuals represented by an RDP selection."""
    qs = qs_individuals_by_household_pks(pks) if master_detail else qs_individuals_by_pks(pks)
    return qs.count()


def qs_individuals_for_rdp(*, rdp: Rdp) -> QuerySet[CountryIndividual]:
    """Return Individuals selected by the RDP household/individual links."""
    master_detail, pks = rdp_selection(rdp=rdp)
    return qs_individuals_by_household_pks(pks) if master_detail else qs_individuals_by_pks(pks)


def collector_pks_by_household_pks(hh_pks: Iterable[int]) -> set[int]:
    """Return PKs of external collectors referenced by the given households' role ref fields."""
    rows = (
        CountryHousehold.objects.filter(pk__in=hh_pks)
        .annotate(
            _primary=KeyTextTransform(HOUSEHOLD_ROLE_REF_FIELDS.primary_collector, "flex_fields"),
            _alternate=KeyTextTransform(HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector, "flex_fields"),
        )
        .values_list("_primary", "_alternate")
    )

    pks: set[int] = set()
    for primary, alternate in rows:
        for ref in (primary, alternate):
            if ref and str(ref).isdigit():
                pks.add(int(ref))
    return pks


def qs_individuals_for_push(hh_pks: Iterable[int]) -> QuerySet[CountryIndividual]:
    """Return household members plus external collectors referenced by role ref fields."""
    hh_pks = list(hh_pks)
    return CountryIndividual.objects.filter(
        Q(household_id__in=hh_pks) | Q(pk__in=collector_pks_by_household_pks(hh_pks))
    ).order_by("id")


def set_rdp_beneficiaries_removed(*, rdp: Rdp, removed: bool) -> None:
    """Set the removed flag for all beneficiaries represented by the RDP."""
    master_detail, pks = rdp_selection(rdp=rdp)
    if master_detail:
        rdp.households.update(removed=removed)
        qs_individuals_by_household_pks(pks).update(removed=removed)
    else:
        rdp.individuals.update(removed=removed)


def append_rdp_log(
    *,
    rdp: Rdp,
    entry_type: RdpLogEntryType,
    result: OperationLogResult | None = None,
) -> None:
    """Append a log entry to an RDP."""
    entry: OperationLogEntry = {
        "timestamp": timezone.now().isoformat(),
        "action": entry_type.value,
    }
    if result is not None:
        entry["result"] = result

    rdp.operation_log = [*(rdp.operation_log or []), entry]
    rdp.save(update_fields=["operation_log"])
