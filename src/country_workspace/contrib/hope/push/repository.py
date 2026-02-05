from collections.abc import Iterable
from django.db.models import QuerySet, Prefetch
from country_workspace.models import Program, Rdp
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


from .config import Serializer, PushWorkflowConfig, Beneficiary
from country_workspace.contrib.hope.constants import PUSH_BATCH_SIZE


def individuals_for_rdp(*, rdp: Rdp) -> QuerySet[CountryIndividual]:
    """Return Individuals queryset using the same selection logic as the push workflow."""
    master_detail, pks = rdp_selection(rdp=rdp)
    return individuals_by_household_pks(pks) if master_detail else individuals_by_pks(pks)


def preflight_errors(pks: list[int], master_detail: bool, exclude_rdp_id: int | None) -> list[str]:
    """Return preflight validation errors for the given selection."""
    if not pks:
        return []

    errors: list[str] = []

    def add(msg: str) -> None:
        errors.append(msg)

    def check(qs: QuerySet[Beneficiary], tag: str) -> None:
        for obj in qs.iterator(chunk_size=PUSH_BATCH_SIZE * 5):
            base = f"{tag} #{obj.pk}"
            if not obj.is_valid():
                add(f"{base} invalid")
            if getattr(obj, "rdp_pre", []):
                add(f"{base} already in another RDP(s) (pending/success)")

    rdp_qs = rdp_pending_or_success(exclude_id=exclude_rdp_id)
    if master_detail:
        check(households_for_preflight(pks=pks, rdp_qs=rdp_qs), "HH")
        check(individuals_for_preflight_by_households(hh_pks=pks, rdp_qs=rdp_qs), "Ind")
    else:
        check(individuals_for_preflight_by_pks(pks=pks, rdp_qs=rdp_qs), "Ind")

    return errors


def serializer_for_program(hope_id: str) -> Serializer:
    """Return a callable row-serializer for the given Program."""
    prog = Program.objects.select_related("serializer").only("serializer_id").get(hope_id=hope_id)
    return prog.serializer.serialize if prog.serializer else (lambda data: data)


def rdp_pending_or_success(*, exclude_id: int | None = None) -> QuerySet[Rdp]:
    """RDPs with PENDING/SUCCESS status; optionally exclude the current RDP."""
    qs = Rdp.objects.filter(status__in=[Rdp.PushStatus.PENDING, Rdp.PushStatus.SUCCESS])
    return qs.exclude(pk=exclude_id) if exclude_id is not None else qs


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def rdp_for_push(*, pk: int) -> Rdp:
    """Return RDP with relations required for push workflow."""
    return Rdp.objects.select_related("program__country_office", "program__beneficiary_group", "pushed_by").get(pk=pk)


def mark_rdp_dedup_finished(*, rdp_id: int) -> None:
    """Mark RDP dedup run as finished."""
    Rdp.objects.filter(pk=rdp_id).update(dedup_run_state=Rdp.DedupRunState.FINISHED)


def _with_rdp_pre(qs: QuerySet[Beneficiary], *, rdp_qs: QuerySet[Rdp]) -> QuerySet[Beneficiary]:
    """Prefetch related RDPs into `rdp_pre` attribute for preflight checks."""
    return qs.prefetch_related(Prefetch("rdp", queryset=rdp_qs, to_attr="rdp_pre"))


def rdp_selection(*, rdp: Rdp) -> tuple[bool, list[int]]:
    """Return (master_detail, pks) based on actual RDP links."""
    hh_pks = list(rdp.households.values_list("pk", flat=True))
    if hh_pks:
        return True, hh_pks
    return False, list(rdp.individuals.values_list("pk", flat=True))


def households_for_preflight(*, pks: Iterable[int], rdp_qs: QuerySet[Rdp]) -> QuerySet[CountryHousehold]:
    """Households with prefetch RDPs for preflight validation."""
    return _with_rdp_pre(households(pks=pks), rdp_qs=rdp_qs)  # type: ignore[return-value]


def individuals_for_preflight_by_households(
    *, hh_pks: Iterable[int], rdp_qs: QuerySet[Rdp]
) -> QuerySet[CountryIndividual]:
    """Individuals (by HH pks) with prefetched RDPs for preflight validation."""
    return _with_rdp_pre(individuals_by_household_pks(hh_pks), rdp_qs=rdp_qs)  # type: ignore[return-value]


def individuals_for_preflight_by_pks(*, pks: Iterable[int], rdp_qs: QuerySet[Rdp]) -> QuerySet[CountryIndividual]:
    """Individuals (by pks) with prefetched RDPs for preflight validation."""
    return _with_rdp_pre(individuals_by_pks(pks), rdp_qs=rdp_qs)  # type: ignore[return-value]


def workflow_config_for_rdp(*, rdp: Rdp, imported_by_email: str) -> PushWorkflowConfig:
    """Build PushWorkflowConfig for pushing an existing RDP."""
    master_detail, pks = rdp_selection(rdp=rdp)
    program = rdp.program
    return {
        "batch_name": rdp.name,
        "co_slug": program.country_office.slug,
        "imported_by_email": imported_by_email,
        "master_detail": master_detail,
        "pks": pks,
        "program_hope_id": program.hope_id,
        "rdp_id": rdp.id,
    }


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
