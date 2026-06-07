from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .exceptions import OnaMappingError


def get_nested_value(data: Mapping[str, Any], path: str) -> Any:
    """
    Supports both:
    1. Flat ONA/ODK keys:
       household/head/name

    2. Nested JSON:
       {"household": {"head": {"name": "Ahmad"}}}
    """
    if path in data:
        return data[path]

    current: Any = data
    for part in path.split("/"):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)

    return current


def map_fields(
    source: Mapping[str, Any],
    field_mapping: Mapping[str, str],
) -> dict[str, Any]:
    """
    Convert ONA field names into Country Workspace/RDI field names.

    Example:
    {
        "hh/name": "full_name",
        "hh/gov": "residence_governorate"
    }
    """
    output: dict[str, Any] = {}

    for ona_field, target_field in field_mapping.items():
        if not target_field:
            raise OnaMappingError(f"Missing target field for ONA field: {ona_field}")

        output[target_field] = get_nested_value(source, ona_field)

    return output


def transform_submission_to_records(
    submission: Mapping[str, Any],
    *,
    master_detail: bool,
    household_field_mapping: Mapping[str, str] | None = None,
    individual_field_mapping: Mapping[str, str] | None = None,
    individuals_key: str = "individuals",
) -> dict[str, Any]:
    """
    Transform one ONA submission into import-ready records.

    For non-master-detail:
        returns one individual record.

    For master-detail:
        returns one household record plus list of individual records.
    """
    household_field_mapping = household_field_mapping or {}
    individual_field_mapping = individual_field_mapping or {}

    source_metadata = {
        "source_submission_id": submission.get("_id"),
        "source_submission_uuid": submission.get("_uuid"),
        "source_submission_time": submission.get("_submission_time"),
    }

    if not master_detail:
        individual = {
            **map_fields(submission, individual_field_mapping),
            **source_metadata,
        }
        return {
            "household": None,
            "individuals": [individual],
        }

    household = {
        **map_fields(submission, household_field_mapping),
        **source_metadata,
    }

    raw_individuals = get_nested_value(submission, individuals_key)

    if raw_individuals is None:
        raw_individuals = []

    if isinstance(raw_individuals, Mapping):
        raw_individuals = [raw_individuals]

    if not isinstance(raw_individuals, list):
        raise OnaMappingError(f"Expected list for individuals_key: {individuals_key}")

    individuals = []
    for index, raw_individual in enumerate(raw_individuals):
        if not isinstance(raw_individual, Mapping):
            raise OnaMappingError(f"Invalid individual at index {index}")

        individuals.append(
            {
                **map_fields(raw_individual, individual_field_mapping),
                **source_metadata,
                "source_individual_index": index,
            }
        )

    return {
        "household": household,
        "individuals": individuals,
    }