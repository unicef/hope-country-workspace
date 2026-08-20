import hashlib
from typing import Any

from django.db import connection

from country_workspace.models import Batch, Individual, Program

COLLECTOR_HASH_FIELDS: tuple[str, ...] = (
    "given_name",
    "middle_name",
    "family_name",
    "full_name",
    "sex",
    "birth_date",
    "phone_no",
    "phone_no_alternative",
)


def normalize_hash_value(value: Any) -> str:
    """Normalize a flex field value for hashing."""
    if value is None:
        return ""
    return str(value).strip().upper()


def compute_collector_hash(flex_fields: dict[str, Any]) -> str | None:
    """Return an identity hash for an external collector, or None if there is nothing to hash.

    Mirrors the field set of HOPE's ``Individual.get_hash_key``. Hash values are
    HCW-internal; they are not meant to match HOPE's. Returns None when every
    identity field is empty — callers should then skip deduplication.
    """
    values = [normalize_hash_value(flex_fields.get(field)) for field in COLLECTOR_HASH_FIELDS]
    if not any(values):
        return None
    return hashlib.sha256(";".join(values).encode()).hexdigest()


def _lock_collector(program_pk: int, identity_hash: str) -> None:
    """Serialize concurrent creation of the same collector across parallel import jobs.

    Transaction-scoped Postgres advisory lock keyed by (program, identity_hash);
    released automatically at the end of the surrounding transaction.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"collector:{program_pk}:{identity_hash}"],
        )


def get_or_create_collector(  # noqa: PLR0913
    *,
    program: Program,
    batch: Batch,
    individual_fields: dict[str, Any],
    raw_data: dict[str, Any],
    originating_id: str,
    name: str = "",
) -> tuple[Individual, bool]:
    """Return the single program-wide Individual for an external collector.

    External collectors (relationship == NON_BENEFICIARY) are deduplicated
    program-wide by identity hash: the first occurrence wins and is reused by
    every later import; its data is never modified. The record is created with
    ``household=None`` — linkage to households happens exclusively through the
    primary/alternate collector role reference fields.
    """
    identity_hash = compute_collector_hash(individual_fields)
    if identity_hash is not None:
        _lock_collector(program.pk, identity_hash)
        existing = (
            Individual.objects.filter(
                batch__program=program, identity_hash=identity_hash, household=None, removed=False
            )
            .order_by("id")
            .first()
        )
        if existing is not None:
            return existing, False
    return (
        Individual.objects.create(
            batch=batch,
            household=None,
            name=name,
            originating_id=originating_id,
            flex_fields=individual_fields,
            raw_data=raw_data,
            identity_hash=identity_hash,
        ),
        True,
    )
