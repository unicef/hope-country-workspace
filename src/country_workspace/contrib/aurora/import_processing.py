from typing import Any, Mapping
from itertools import chain
from copy import deepcopy
from collections.abc import Iterable

from django.db import transaction

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.models import AsyncJob, Batch, Individual
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import clean_field_names


class Config(BatchNameConfig, ValidateModeConfig):
    registration_reference_pk: str | None
    master_detail: bool


def import_from_aurora(job: AsyncJob) -> dict[str, int]:
    config: Config = job.config

    if not config.get("registration_reference_pk"):
        return {"errors": ["registration_reference_pk is required for Aurora import"]}

    with transaction.atomic():
        batch = Batch.objects.create(
            name=config["batch_name"],
            program=job.program,
            country_office=job.program.country_office,
            imported_by=job.owner,
            source=Batch.BatchSource.AURORA,
        )

        if config["master_detail"]:
            raise NotImplementedError
        return _import_people(job, batch, config)


def _import_people(job: AsyncJob, batch: Batch, config: Config) -> dict[str, int]:
    client = AuroraClient()
    people_counter = 0

    for record in client.get(f"registration/{config['registration_reference_pk']}/records/"):
        normalized_row = flatten_top2_prefixed(record["fields"])
        cleaned_fieldnames_row = clean_field_names(normalized_row)
        if not (cleaned_fieldnames_row.get("full_name") or "").strip() and (
            fullname := make_full_name(cleaned_fieldnames_row)
        ):
            cleaned_fieldnames_row["full_name"] = fullname
        flex_fields = job.program.apply_mapping_importer(Individual, deepcopy(cleaned_fieldnames_row))
        Individual.objects.create(
            batch_id=batch.pk,
            name="",
            household=None,
            flex_fields=flex_fields,
            raw_data=record,
        )
        people_counter += 1

    return {"people": people_counter}


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
