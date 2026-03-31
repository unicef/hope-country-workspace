from collections.abc import Iterable
from typing import Any

from country_workspace.models import Individual

COLLECTOR_ID_FIELD = "collector_id"
REFERENCE_FIELDS = ("individual_id", "index_id")


def _normalize_reference(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip() or None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None

    cleaned = str(value).strip()
    return cleaned or None


def sync_collector_links(individuals: Iterable[Individual]) -> int:
    individuals_list = list(individuals)
    reference_pk_map: dict[str, int] = {}

    individuals_to_process = [individual for individual in individuals_list if individual.flex_fields]
    reference_pk_map = {
        reference: individual.pk
        for individual in individuals_to_process
        for field in REFERENCE_FIELDS
        if (reference := _normalize_reference(individual.flex_fields.get(field)))
    }

    updates: list[Individual] = []
    for individual in individuals_to_process:
        collector_reference = _normalize_reference(individual.flex_fields.get(COLLECTOR_ID_FIELD))
        if not collector_reference:
            continue

        collector_pk = reference_pk_map.get(collector_reference)
        if collector_pk is None or individual.flex_fields.get(COLLECTOR_ID_FIELD) == collector_pk:
            continue

        individual.flex_fields = {**individual.flex_fields, COLLECTOR_ID_FIELD: collector_pk}
        updates.append(individual)

    if updates:
        Individual.objects.bulk_update(updates, ["flex_fields"])

    return len(updates)
