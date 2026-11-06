from collections.abc import Iterator
from datetime import date, datetime
from itertools import batched
from typing import TYPE_CHECKING, Any, cast

from country_workspace.contrib.biographic_dedup.schemas import BiographicPayload, BiographicRecord
from country_workspace.rdp.repository import qs_individuals_for_rdp

from .constants import (
    BIOGRAPHIC_BIRTH_DATE_FIELD,
    BIOGRAPHIC_FULL_NAME_FIELD,
    BIOGRAPHIC_RECORDS_BATCH_SIZE,
    BIOGRAPHIC_TEXT_FIELDS,
)

if TYPE_CHECKING:
    from country_workspace.contrib.biographic_dedup.client import BiographicClient
    from country_workspace.models import Individual, Rdp


def _clean_text(value: Any) -> str | None:
    """Return a stripped string, or None when there is nothing to score."""
    if value is None or isinstance(value, bool):
        return None
    return str(value).strip() or None


def _clean_birth_date(value: Any) -> str | None:
    """Return an ISO date, or None when the value is not a valid date.

    DedupEngine rejects the whole batch on a malformed date, so an unparseable value is
    dropped: the person is still matched by name and the remaining fields.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if (text := _clean_text(value)) is None:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def build_biographic_record(individual: "Individual") -> BiographicRecord | None:
    """Build the DedupEngine record of an individual.

    Returns None when the individual has no name: `full_name` is the one field DedupEngine
    requires, and a person without a name cannot be matched.
    """
    flex_fields = individual.flex_fields or {}
    full_name = _clean_text(flex_fields.get(BIOGRAPHIC_FULL_NAME_FIELD)) or _clean_text(individual.name)
    if full_name is None:
        return None

    payload: dict[str, Any] = {BIOGRAPHIC_FULL_NAME_FIELD: full_name}
    for field in BIOGRAPHIC_TEXT_FIELDS:
        payload[field] = _clean_text(flex_fields.get(field))
    payload[BIOGRAPHIC_BIRTH_DATE_FIELD] = _clean_birth_date(flex_fields.get(BIOGRAPHIC_BIRTH_DATE_FIELD))

    return {"reference_pk": str(individual.pk), "payload": cast("BiographicPayload", payload)}


class BiographicDedupProcessor:
    """Build and upload biographic deduplication input for an RDP."""

    def __init__(self, rdp: "Rdp") -> None:
        self.rdp = rdp

    def _iter_records(self) -> Iterator[BiographicRecord]:
        """Yield DedupEngine records for the RDP individuals that have a name."""
        qs = qs_individuals_for_rdp(rdp=self.rdp).only("id", "name", "flex_fields")
        for individual in qs.iterator(chunk_size=BIOGRAPHIC_RECORDS_BATCH_SIZE):
            if record := build_biographic_record(individual):
                yield record

    def has_records(self) -> bool:
        """Return whether the RDP has at least one individual DedupEngine can match."""
        return next(self._iter_records(), None) is not None

    def upload_records(self, client: "BiographicClient") -> int:
        """Upload the RDP individuals in batches and return the number submitted."""
        sent = 0
        for batch in batched(self._iter_records(), BIOGRAPHIC_RECORDS_BATCH_SIZE, strict=False):
            client.upload_records(list(batch))
            sent += len(batch)
        return sent
