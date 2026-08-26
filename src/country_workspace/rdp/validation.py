from collections.abc import Iterable
from django.db.models import Exists, OuterRef, QuerySet

from country_workspace.rdp.constants import PUSH_BATCH_SIZE
from country_workspace.models import Rdp
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.rdp.repository import qs_individuals_for_push


def _is_valid_row(*, last_checked: object, errors: object) -> bool | None:
    if last_checked is None:
        return None
    return not bool(errors)


def preflight_errors(
    pks: list[int],
    master_detail: bool,
    exclude_rdp_ids: Iterable[int] = (),
) -> list[str]:
    """Return preflight validation errors for the given selection."""
    if not pks:
        return ["RDP: no beneficiaries selected"]

    rdp_qs = Rdp.objects.filter(status__in=[*NON_TERMINAL_RDP_STATUSES, Rdp.PushStatus.SUCCESS])
    if excluded := tuple(exclude_rdp_ids):
        rdp_qs = rdp_qs.exclude(pk__in=excluded)

    def collect(rows: QuerySet, tag: str) -> list[str]:
        errors: list[str] = []
        for pk, last_checked, obj_errors, has_rdp in rows.iterator(chunk_size=PUSH_BATCH_SIZE * 5):
            base = f"{tag} #{pk}"
            if not _is_valid_row(last_checked=last_checked, errors=obj_errors):
                errors.append(f"{base} invalid")
            if has_rdp:
                errors.append(f"{base} already in another RDP(s) (open/success)")
        return errors

    def individual_rows() -> QuerySet:
        qs = qs_individuals_for_push(pks) if master_detail else CountryIndividual.objects.filter(pk__in=pks)
        return (
            qs.order_by("id")
            .annotate(has_rdp=Exists(rdp_qs.filter(individuals=OuterRef("pk"))))
            .values_list("pk", "last_checked", "errors", "has_rdp")
        )

    errors = collect(individual_rows(), "Ind")
    if not master_detail:
        return errors

    household_rows = (
        CountryHousehold.objects.filter(pk__in=pks)
        .order_by("id")
        .annotate(has_rdp=Exists(rdp_qs.filter(households=OuterRef("pk"))))
        .values_list("pk", "last_checked", "errors", "has_rdp")
    )
    return collect(household_rows, "HH") + errors
