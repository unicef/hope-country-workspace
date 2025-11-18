from typing import Any, Mapping, NamedTuple
from itertools import chain
from copy import deepcopy
from collections.abc import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Individual, SyncLog, Program
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import clean_field_names
from country_workspace.utils.sync_log import get_aurora_sync_log_name


class Config(BatchNameConfig, ValidateModeConfig):
    registration_reference_pk: str | None
    master_detail: bool


class ImportResult(NamedTuple):
    people: int


def import_data(job: AsyncJob) -> ImportResult:
    config: Config = job.config
    if config.get("master_detail"):
        raise NotImplementedError
    if not config.get("registration_reference_pk"):
        raise ImportError("registration_reference_pk is required for Aurora import")

    batch = Batch.objects.create(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.AURORA,
    )

    total_people = 0
    client = AuroraClient()
    for result in client.get(f"registration/{config['registration_reference_pk']}/records/"):
        imported = import_result(batch, result, config)
        total_people += imported.people
    return ImportResult(people=total_people)


def import_result(batch: Batch, result: Mapping[str, Any], config: Config) -> ImportResult:
    people_counter = 0
    sync_log_name = get_aurora_sync_log_name(config["registration_reference_pk"])
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLog.objects.filter(name=sync_log_name, content_type=program_ct, object_id=batch.program.id).first()
    last_id = int(sync_log.last_id) if sync_log and sync_log.last_id else 0
    last_successful_id = last_id

    try:
        current_id = int(result["pk"])
        if current_id <= last_id:
            return ImportResult(people=0)
        with transaction.atomic():
            create_people(batch, result, config)
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
    return ImportResult(people=people_counter)


def create_people(batch: Batch, record: dict[str, Any], config: Config) -> Individual:
    normalized_row = flatten_top2_prefixed(record["fields"])
    cleaned_fieldnames_row = clean_field_names(normalized_row)
    if not (cleaned_fieldnames_row.get("full_name") or "").strip() and (
        fullname := make_full_name(cleaned_fieldnames_row)
    ):
        cleaned_fieldnames_row["full_name"] = fullname
    flex_fields = batch.program.apply_mapping_importer(Individual, deepcopy(cleaned_fieldnames_row))
    return Individual.objects.create(
        batch_id=batch.pk,
        name="",
        household=None,
        flex_fields=flex_fields,
        raw_data=record,
    )


def flatten_top2_prefixed(
    data: Mapping[str, Any] | list[Mapping[str, Any]],
    *,
    prefixes: Mapping[str, str] | None = None,
    sep: str = "_",
) -> dict[str, Any]:
    """Flatten top level; prefix-expand second-level dicts by parent key; ignore deeper nesting."""
    pref = prefixes or {}
    out: dict[str, Any] = {}

    def ld2d(items: list[Mapping[str, Any]]) -> dict[str, Any]:
        return dict(chain.from_iterable(d.items() for d in items))

    def merge(d: Mapping[str, Any]) -> None:
        for k, v in d.items():
            if isinstance(v, Mapping):  # 2nd level dict
                p = pref.get(k, k)
                out.update({f"{p}{sep}{kk}": vv for kk, vv in v.items()})
            elif isinstance(v, list) and all(isinstance(it, Mapping) for it in v):  # list[dict]
                merge(ld2d(v))  # treat elements as top level
            else:
                out[k] = v

    if isinstance(data, Mapping):
        merge(data)
    elif isinstance(data, list):
        merge(ld2d([it for it in data if isinstance(it, Mapping)]))
    return out


def make_full_name(row: Mapping[str, Any], keys: Iterable[str] = ("given_name", "middle_name", "family_name")) -> str:
    parts = (str(row.get(k) or "").strip() for k in keys)
    return " ".join(p for p in parts if p)
