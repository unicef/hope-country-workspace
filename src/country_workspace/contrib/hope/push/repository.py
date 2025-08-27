from collections.abc import Iterable
from django.db.models import QuerySet, Prefetch
from country_workspace.models import Program, Rdp
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from .config import Serializer


def serializer_for_program(hope_id: str) -> Serializer:
    """Return a callable row-serializer for the given Program."""
    prog = Program.objects.select_related("serializer").only("serializer_id").get(hope_id=hope_id)
    return prog.serializer.serialize if prog.serializer else (lambda data: data)


def rdp_pending_or_success(exclude_id: int | None) -> QuerySet[Rdp]:
    """RDPs with PENDING/SUCCESS status, exclude the current RDP."""
    return Rdp.objects.filter(status__in=[Rdp.PushStatus.PENDING, Rdp.PushStatus.SUCCESS]).exclude(pk=exclude_id)


def individuals_for_preflight_by_households(
    *, hh_pks: Iterable[int], rdp_qs: QuerySet[Rdp]
) -> QuerySet[CountryIndividual]:
    """Individuals (by HH pks) with prefetch RDPs for preflight validation."""
    return individuals_by_household_pks(hh_pks).prefetch_related(Prefetch("rdp", queryset=rdp_qs, to_attr="rdp_pre"))


def households_for_preflight(*, pks: Iterable[int], rdp_qs: QuerySet[Rdp]) -> QuerySet[CountryHousehold]:
    """Households with prefetch RDPs for preflight validation."""
    return households(pks=pks).prefetch_related(Prefetch("rdp", queryset=rdp_qs, to_attr="rdp_pre"))


def individuals_for_preflight_by_pks(*, pks: Iterable[int], rdp_qs: QuerySet[Rdp]) -> QuerySet[CountryIndividual]:
    """Individuals (by pks) with prefetched RDPs for preflight validation."""
    return individuals_by_pks(pks).prefetch_related(Prefetch("rdp", queryset=rdp_qs, to_attr="rdp_pre"))


def individuals_by_household_pks(hh_pks: Iterable[int]) -> QuerySet[CountryIndividual]:
    """Individuals filtered by household ids; ordered by primary key."""
    return CountryIndividual.objects.filter(household_id__in=hh_pks).order_by("id")


def individuals_by_pks(pks: Iterable[int]) -> QuerySet[CountryIndividual]:
    """Individuals filtered by primary keys; ordered by primary key."""
    return CountryIndividual.objects.filter(pk__in=pks).order_by("id")


def households(*, pks: Iterable[int], prefetch_members: bool = True) -> QuerySet[CountryHousehold]:
    """Households filtered by primary keys; ordered by primary key; prefetch members to 'prefetched_members'."""
    qs = CountryHousehold.objects.filter(pk__in=pks).order_by("id")
    if prefetch_members:
        qs = qs.prefetch_related(
            Prefetch(
                "members",
                queryset=CountryIndividual.objects.only("id").order_by("id"),
                to_attr="prefetched_members",
            )
        )
    return qs
