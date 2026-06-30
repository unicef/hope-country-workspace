import logging
from typing import Any, NamedTuple, NotRequired, Callable
from itertools import chain
from collections.abc import Mapping

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs
from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.crypto import decrypt_record_fields
from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import AsyncJob, Batch, Individual, SyncLog, Program, Household
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.imports import get_aurora_originating_id
from country_workspace.utils.import_flow import build_import_processor, run_batch_postprocessing
from country_workspace.utils.sync_log import get_aurora_sync_log_name

logger = logging.getLogger(__name__)


class Config(BatchNameConfig, ValidateModeConfig):
    registration_reference_pk: str | None
    master_detail: bool
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]
    household_transformer_id: NotRequired[int | None]
    individual_transformer_id: NotRequired[int | None]


class ImportResult(NamedTuple):
    people: int
    households: int = 0


def _load_rsa_private_key(registration_reference_pk: str) -> str:
    registration = Registration.objects.filter(reference_pk=int(registration_reference_pk)).first()
    if registration is None:
        return ""
    return (registration.rsa_private_key or "").strip()


def prepare_record(record: Mapping[str, Any], private_key: str) -> dict[str, Any]:
    result = dict(record)
    fields = result.get("fields")
    if fields is None or isinstance(fields, dict):
        return result
    if not isinstance(fields, str):
        msg = f"Record {result.get('pk')}: unsupported encrypted fields payload type"
        raise TypeError(msg)
    if not private_key:
        msg = (
            f"Record {result.get('pk')}: encrypted Aurora registration requires an RSA private key "
            "on the CW Registration"
        )
        raise ImportError(msg)
    try:
        result["fields"] = decrypt_record_fields(fields, private_key)
    except Exception as exc:
        msg = f"Record {result.get('pk')}: failed to decrypt fields"
        raise ImportError(msg) from exc
    return result


def import_data(job: AsyncJob) -> ImportResult:
    config: Config = job.config
    job.ensure_not_cancelled(refresh=True)
    if not config.get("registration_reference_pk"):
        raise ImportError("registration_reference_pk is required for Aurora import")

    private_key = _load_rsa_private_key(str(config["registration_reference_pk"]))

    batch = Batch.objects.create(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.AURORA,
        status=Batch.BatchStatus.LOADING,
    )
    job.batch = batch
    job.save(update_fields=["batch"])

    total_people = 0
    total_households = 0
    client = AuroraClient()
    for result in client.get(f"registration/{config['registration_reference_pk']}/records/"):
        job.ensure_not_cancelled(refresh=True)
        imported = import_result(batch, result, config, private_key=private_key)
        total_people += imported.people
        total_households += imported.households

    job.ensure_not_cancelled(refresh=True)

    run_batch_postprocessing(
        batch,
        household_transformer_id=config.get("household_transformer_id"),
        individual_transformer_id=config.get("individual_transformer_id"),
    )

    job.ensure_not_cancelled(refresh=True)
    if config.get("validate_after_import"):
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=job.program,
            queryset=_validation_queryset(batch, config),
        )

    batch.status = Batch.BatchStatus.COMPLETE
    batch.save(update_fields=["status"])
    return ImportResult(people=total_people, households=total_households)


def import_result(
    batch: Batch,
    result: Mapping[str, Any],
    config: Config,
    *,
    private_key: str = "",
) -> ImportResult:
    people_counter = 0
    household_counter = 0
    sync_log_name = get_aurora_sync_log_name(f"registration{config['registration_reference_pk']}")
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLog.objects.filter(name=sync_log_name, content_type=program_ct, object_id=batch.program.id).first()
    last_id = int(sync_log.last_id) if sync_log and sync_log.last_id else 0
    last_successful_id = last_id

    try:
        pk_value = result.get("pk")
        if pk_value is None:
            raise ValueError("Missing record pk")  # noqa: TRY301
        current_id = int(pk_value)
        if current_id <= last_id:
            return ImportResult(people=0)
        with transaction.atomic():
            record = prepare_record(result, private_key)
            originating_id = get_aurora_originating_id(record["pk"])
            if config.get("master_detail"):
                created_households, created_individuals = create_household_and_individuals(
                    batch, record, config, originating_id
                )
                household_counter += created_households
                people_counter += created_individuals
            else:
                create_individual(batch, record, config, originating_id)
                people_counter += 1
            last_successful_id = current_id
    except Exception as e:
        failed_id = result.get("pk", "unknown (before first record)")
        error_msg = (
            f"Successfully imported {people_counter} people, before stopping at record {failed_id} due to:\n"
            f"Error: {e}\n"
            f"Last successful record ID: {last_successful_id}."
        )
        raise ImportError(error_msg) from e
    finally:
        if last_successful_id > last_id:
            SyncLog.objects.update_or_create(
                name=sync_log_name,
                content_type=program_ct,
                object_id=batch.program.id,
                defaults={"last_id": str(last_successful_id), "last_update_date": timezone.now()},
            )
    return ImportResult(people=people_counter, households=household_counter)


def create_individual(
    batch: Batch,
    record: Mapping[str, Any],
    config: Config,
    originating_id: str,
    **extras: Any,
) -> Individual:
    row = record.get("fields", record)
    individual_row_processor = build_individual_processor(
        batch.program,
        mapping_id=config.get("individual_mapping_id"),
    )
    extras.setdefault("household", None)
    return Individual.objects.create(
        batch_id=batch.pk,
        name="",
        originating_id=originating_id,
        flex_fields=individual_row_processor(row),
        raw_data=record,
        **extras,
    )


def create_household(batch: Batch, record: Mapping[str, Any], config: Config, originating_id: str) -> Household:
    row = record.get("fields", record)
    household_row_processor = build_household_processor(
        batch.program,
        mapping_id=config.get("household_mapping_id"),
    )
    return Household.objects.create(
        batch_id=batch.pk,
        name="",
        originating_id=originating_id,
        flex_fields=household_row_processor(row),
        raw_data=record,
    )


def create_household_and_individuals(
    batch: Batch, record: Mapping[str, Any], config: Config, originating_id: str
) -> tuple[int, int]:
    fields = record.get("fields", {})
    household_candidates = ("household", "household-info", "household_info")
    individual_candidates = ("individuals", "individual-details", "individual_details")

    def _extract_group(keys: tuple[str, ...]) -> list[Mapping[str, Any]] | None:
        for key in keys:
            if not fields.get(key):
                continue

            value = fields[key]
            if isinstance(value, list):
                return value
            if isinstance(value, Mapping):
                return [value]
        return None

    households_data = _extract_group(household_candidates)
    individuals_data = _extract_group(individual_candidates)

    households_data = households_data or []
    individuals_data = individuals_data or []

    group_keys = set(household_candidates) | set(individual_candidates)
    shared_fields = {k: v for k, v in fields.items() if k not in group_keys and k is not None}
    household_raw = households_data[0] if households_data else {}
    household_fields = {**shared_fields, **household_raw}

    household = create_household(batch, household_fields, config, f"{originating_id}#HH0")
    people_counter = 0
    for idx, individual_raw in enumerate(individuals_data):
        try:
            individual_fields = {**shared_fields, **individual_raw}
            create_individual(
                batch,
                individual_fields,
                config,
                f"{originating_id}#IND{idx}",
                household=household,
            )
            people_counter += 1
        except Exception as exc:
            raise ImportError(f"Failed to create Aurora individual #{idx} for record {originating_id}") from exc

    return 1, people_counter


def flatten_top2_prefixed(
    data: Mapping[str, Any],
    sep: str = "_",
) -> dict[str, Any]:
    """Flatten top level; prefix-expand second-level dicts by parent key; ignore deeper nesting."""
    out: dict[str, Any] = {}

    def ld2d(items: list[Mapping[str, Any]]) -> dict[str, Any]:
        return dict(chain.from_iterable(d.items() for d in items))

    def merge(d: Mapping[str, Any]) -> None:
        for k, v in d.items():
            if isinstance(v, Mapping):  # 2nd level dict
                out.update({f"{k}{sep}{kk}": vv for kk, vv in v.items()})
            elif isinstance(v, list) and all(isinstance(it, Mapping) for it in v):  # list[dict]
                merge(ld2d(v))
            else:
                out[k] = v

    merge(data)
    return out


def make_full_name(row: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
    if (row.get("full_name") or "").strip():
        return row

    parts = [(row.get(k) or "").strip() for k in ("given_name", "middle_name", "family_name")]
    if full := " ".join(p for p in parts if p):
        row["full_name"] = full

    return row


def build_individual_processor(
    program: Program, mapping_id: int | None = None
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return build_import_processor(
        program=program,
        model=Individual,
        mapping_id=mapping_id,
        pre_processors=(flatten_top2_prefixed,),
        post_processors=(make_full_name,),
        source=Batch.BatchSource.AURORA,
    )


def build_household_processor(
    program: Program, mapping_id: int | None = None
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    return build_import_processor(
        program=program,
        model=Household,
        mapping_id=mapping_id,
        pre_processors=(flatten_top2_prefixed,),
        post_processors=(make_full_name,),
        source=Batch.BatchSource.AURORA,
    )


def _validation_queryset(batch: Batch, config: Config) -> QuerySet[Household | Individual]:
    if config.get("master_detail"):
        return batch.household_set.filter(removed=False).prefetch_related("members")
    return batch.individual_set.filter(household__isnull=True, removed=False)
