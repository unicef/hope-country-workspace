from collections.abc import Iterable
from uuid import UUID, uuid4

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.hope.constants import PUSH_BATCH_SIZE
from country_workspace.models import AsyncJob, Program, Rdp
from country_workspace.models.rdp import NON_TERMINAL_RDP_STATUSES
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual

from .config import OperationLogEntry, OperationLogResult, PushAttemptJobConfig, PushWorkflowConfig, Serializer


def lock_rdp_for_update(*, pk: int) -> Rdp:
    """Return RDP locked for update."""
    return Rdp.objects.select_for_update().select_related("program").get(pk=pk)


def rdp_for_dedup(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for dedup workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def rdp_for_push(*, pk: int) -> Rdp:
    """Return RDP with relations required for push workflow."""
    return Rdp.objects.select_related(
        "program__country_office",
        "program__beneficiary_group",
        "pushed_by",
    ).get(pk=pk)


def rdp_selection(*, rdp: Rdp) -> tuple[bool, list[int]]:
    """Return the RDP selection mode and beneficiary IDs."""
    master_detail = rdp.program.beneficiary_group.master_detail
    beneficiaries = rdp.households if master_detail else rdp.individuals
    return master_detail, list(beneficiaries.order_by("pk").values_list("pk", flat=True))


def serializer_for_program(hope_id: str) -> Serializer:
    """Return a callable row-serializer for the given Program."""
    prog = Program.objects.select_related("serializer").only("serializer_id").get(hope_id=hope_id)
    return prog.serializer.serialize if prog.serializer else (lambda data: data)


def workflow_config_for_rdp(*, rdp: Rdp, imported_by_email: str) -> PushWorkflowConfig:
    """Build push workflow config for an existing RDP."""
    master_detail, pks = rdp_selection(rdp=rdp)
    program = rdp.program
    config: PushWorkflowConfig = {
        "batch_name": rdp.name or str(rdp),
        "co_slug": program.country_office.slug,
        "imported_by_email": imported_by_email,
        "master_detail": master_detail,
        "pks": pks,
        "program_hope_id": program.hope_id,
        "rdp_id": rdp.id,
    }
    if program.biometric_deduplication_enabled and rdp.deduplication_set_id:
        config["country_workspace_id"] = str(rdp.deduplication_set_id)
    return config


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
    """Return household members plus external collectors referenced by role ref fields.

    External collectors (relationship == NON_BENEFICIARY) have household=None and
    are linked to households only through the primary/alternate collector role
    reference fields, so they must be included explicitly to be pushed to HOPE.
    """
    hh_pks = list(hh_pks)
    return CountryIndividual.objects.filter(
        Q(household_id__in=hh_pks) | Q(pk__in=collector_pks_by_household_pks(hh_pks))
    ).order_by("id")


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


def set_rdp_push_status(
    *,
    rdp: Rdp,
    status: Rdp.PushStatus,
    hope_rdi_id: str,
    is_dedup_settings_locked: bool | None = None,
    is_push_locked: bool | None = None,
) -> None:
    """Persist push status fields for an already-locked RDP."""
    rdp.status = status
    rdp.hope_rdi_id = hope_rdi_id
    update_fields = ["status", "hope_rdi_id"]
    if is_dedup_settings_locked is not None:
        rdp.is_dedup_settings_locked = is_dedup_settings_locked
        update_fields.append("is_dedup_settings_locked")
    if is_push_locked is not None:
        rdp.is_push_locked = is_push_locked
        update_fields.append("is_push_locked")
    rdp.save(update_fields=update_fields)


def start_rdp_push_attempt(*, rdp: Rdp) -> UUID:
    """Start a new push attempt for an already-locked RDP."""
    push_attempt_id = uuid4()
    rdp.status = Rdp.PushStatus.PUSH_PENDING
    rdp.is_push_locked = True
    rdp.push_attempt_id = push_attempt_id
    rdp.save(
        update_fields=[
            "status",
            "is_push_locked",
            "push_attempt_id",
        ]
    )
    return push_attempt_id


def lock_rdp_push_attempt(*, rdp_id: int, push_attempt_id: UUID) -> Rdp | None:
    """Lock and return the matching active RDP push attempt."""
    return (
        Rdp.objects.select_for_update()
        .select_related("program")
        .filter(
            pk=rdp_id,
            status=Rdp.PushStatus.PUSH_PENDING,
            is_push_locked=True,
            push_attempt_id=push_attempt_id,
        )
        .first()
    )


def finish_rdp_push_attempt(*, rdp: Rdp, status: Rdp.PushStatus, hope_rdi_id: str) -> None:
    """Finish an already-locked RDP push attempt."""
    rdp.status = status
    rdp.hope_rdi_id = hope_rdi_id
    rdp.is_push_locked = False
    rdp.push_attempt_id = None
    rdp.save(
        update_fields=[
            "status",
            "hope_rdi_id",
            "is_push_locked",
            "push_attempt_id",
        ]
    )


def release_rdp_dedup_settings_lock(*, rdp_id: int) -> None:
    """Release the dedup settings lock for an RDP."""
    Rdp.objects.filter(pk=rdp_id, is_dedup_settings_locked=True).update(is_dedup_settings_locked=False)


def append_rdp_operation_log(
    *,
    rdp: Rdp,
    action: Rdp.OperationAction,
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
