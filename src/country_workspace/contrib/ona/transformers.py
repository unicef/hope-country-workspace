from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .exceptions import OnaMappingError


def get_nested_value(data: Mapping[str, Any], path: str) -> Any:
    """
    Support flat ONA/ODK keys and nested JSON.

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


def remove_nested_value(data: Mapping[str, Any], path: str) -> dict[str, Any]:
    """Return a copy of ONA data with a flat or nested slash-path removed."""
    output = dict(data)

    if path in output:
        output.pop(path, None)
        return output

    parts = path.split("/")
    source: Mapping[str, Any] = data
    target = output

    for part in parts[:-1]:
        child = source.get(part)
        if not isinstance(child, Mapping):
            return output

        child_copy = dict(child)
        target[part] = child_copy
        target = child_copy
        source = child

    target.pop(parts[-1], None)
    return output


def flatten_ona_data(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested ONA/ODK JSON into slash-separated source field names."""
    output: dict[str, Any] = {}

    for key, value in data.items():
        path = f"{prefix}/{key}" if prefix else str(key)

        if isinstance(value, Mapping):
            output.update(flatten_ona_data(value, path))
        else:
            output[path] = value

    return output


def filter_ona_sys_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Remove ONA/ODK system fields such as _id, _uuid, and _submission_time."""
    return {
        key: value
        for key, value in data.items()
        if not key.split("/")[-1].startswith("_")
    }


def transform_submission_to_records(
    submission: Mapping[str, Any],
    *,
    master_detail: bool,
    individuals_key: str = "individuals",
) -> dict[str, Any]:
    """
    Transform one ONA submission into source records with separate raw source data.

    For non-master-detail:
        returns one individual record.

    For master-detail:
        returns one household record plus list of individual records.
    """
    if not master_detail:
        return {
            "household": None,
            "individuals": [
                {
                    "fields": dict(submission),
                    "raw_data": dict(submission),
                }
            ],
        }

    raw_individuals = get_nested_value(submission, individuals_key)

    if raw_individuals is None:
        raw_individuals = []

    if isinstance(raw_individuals, Mapping):
        raw_individuals = [raw_individuals]

    if not isinstance(raw_individuals, list):
        raise OnaMappingError(f"Expected list for individuals_key: {individuals_key}")

    raw_household = remove_nested_value(submission, individuals_key)

    individuals = []
    for index, raw_individual in enumerate(raw_individuals):
        if not isinstance(raw_individual, Mapping):
            raise OnaMappingError(f"Invalid individual at index {index}")

        individuals.append(
            {
                "fields": dict(raw_individual),
                "raw_data": dict(raw_individual),
            }
        )

    return {
        "household": {
            "fields": raw_household,
            "raw_data": raw_household,
        },
        "individuals": individuals,
    }
