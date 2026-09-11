from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Prefetch
from django.urls import reverse

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from country_workspace.models.base import Validable


DATA_URI_FORMAT = "data:{mimetype};base64,{content}"
DATA_URI_PREFIX = "data:"
DEFAULT_MIMETYPE = "application/octet-stream"
PREFETCH_NAME = "flex_field_files"
FLEX_FILE_URL_NAME = "workspace:flex_file"
PENDING_PREFIX = "flexfile-pending:"


@dataclass(frozen=True, slots=True)
class FlexFileContent:
    """Raw file payload travelling from a producer to `write_flex_file`.

    Producers keep the bytes out of the data they build, since that data is
    stored as JSON, and pass these alongside it instead.
    """

    content: bytes
    mimetype: str = DEFAULT_MIMETYPE
    filename: str = ""


def as_data_uri(flex_file: FlexFieldFile) -> str:
    return DATA_URI_FORMAT.format(
        mimetype=flex_file.mimetype or DEFAULT_MIMETYPE,
        content=b64encode(flex_file.content_bytes).decode(),
    )


def write_flex_file(
    record: "Validable",
    field_name: str,
    content: bytes,
    mimetype: str = DEFAULT_MIMETYPE,
    filename: str = "",
) -> str:
    """Store `content` for `record.field_name` and return its reference.

    Rows are append-only: an existing row for the same content is reused, any
    other row is left untouched, so previous references stay resolvable.
    """
    checksum = hashlib.sha256(content).hexdigest()
    # proxy models resolve to their concrete model, so proxy and concrete rows never diverge
    content_type = ContentType.objects.get_for_model(record, for_concrete_model=True)
    existing = (
        FlexFieldFile.objects.filter(
            content_type=content_type,
            object_id=record.pk,
            field_name=field_name,
            checksum=checksum,
        )
        .order_by("created_at")
        .first()
    )
    if existing:
        return existing.reference

    flex_file = FlexFieldFile.objects.create(
        content_type=content_type,
        object_id=record.pk,
        field_name=field_name,
        content=content,
        mimetype=mimetype or DEFAULT_MIMETYPE,
        size=len(content),
        original_filename=filename or "",
        checksum=checksum,
    )
    return flex_file.reference


def attach_flex_files(
    record: "Validable",
    files: Mapping[str, FlexFileContent],
    *,
    update_raw_data: bool = True,
    save: bool = True,
) -> dict[str, str]:
    """Write file rows for an existing record and store their references.

    References go into `flex_fields` and, unless disabled, into `raw_data`, so
    that reprocessing from `raw_data` keeps the originally imported files.
    """
    if not files:
        return {}

    with transaction.atomic():
        references = {
            field_name: write_flex_file(record, field_name, item.content, item.mimetype, item.filename)
            for field_name, item in files.items()
        }
        record.flex_fields = {**(record.flex_fields or {}), **references}
        update_fields = ["flex_fields"]
        if update_raw_data:
            record.raw_data = {**(record.raw_data or {}), **references}
            update_fields.append("raw_data")
        if save:
            record.save(update_fields=update_fields)

    return references


def pending_marker(key: str) -> str:
    """Return a placeholder standing in for a file until the owning record exists.

    Importers put it in the payload that becomes `raw_data`, so that column
    mapping still applies to file-typed columns, and keep the bytes aside under
    the same `key`.
    """
    return "%s%s" % (PENDING_PREFIX, key)


def _parse_pending_marker(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(PENDING_PREFIX):
        return value.removeprefix(PENDING_PREFIX)
    return None


def materialize_pending_files(
    record: "Validable",
    files: Mapping[str, FlexFileContent],
    *,
    save: bool = True,
) -> dict[str, str]:
    """Replace the pending markers of a freshly imported record with references.

    Both `flex_fields` and `raw_data` are scanned, so a mapped file column ends
    up referenced under its flex field name and under its source column name.
    """
    if not files:
        return {}

    flex_fields = dict(record.flex_fields or {})
    raw_data = dict(record.raw_data or {})
    references: dict[str, str] = {}

    with transaction.atomic():
        resolved_flex = _resolve_markers(record, flex_fields, files, references)
        resolved_raw = _resolve_markers(record, raw_data, files, references)
        if not resolved_flex and not resolved_raw:
            return {}

        update_fields = []
        if resolved_flex:
            record.flex_fields = {**flex_fields, **resolved_flex}
            update_fields.append("flex_fields")
        if resolved_raw:
            record.raw_data = {**raw_data, **resolved_raw}
            update_fields.append("raw_data")
        if save:
            record.save(update_fields=update_fields)

    return resolved_flex


def resolve_flex_files(record: "Validable", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return `payload` with references expanded into data-URIs.

    Legacy inline data-URIs are passed through untouched. A reference the record
    does not own raises, since incomplete data must not reach an external system.
    """
    data = dict(payload if payload is not None else (record.flex_fields or {}))
    references: dict[str, UUID] = {}
    for name, value in data.items():
        if (file_id := FlexFieldFile.parse_reference(value)) is not None:
            references[name] = file_id
    if not references:
        return data

    files = _load_files(record, set(references.values()))
    for name, file_id in references.items():
        if (flex_file := files.get(file_id)) is None:
            raise MissingFlexFileError(
                f"{type(record).__name__} #{record.pk}: field {name!r} references missing file {data[name]}"
            )
        data[name] = as_data_uri(flex_file)
    return data


def prefetch_flex_files(queryset: "QuerySet[Any]") -> "QuerySet[Any]":
    return queryset.prefetch_related(
        Prefetch(PREFETCH_NAME, queryset=FlexFieldFile.objects.with_content()),
    )


def _flex_file_url(reference: Any) -> str | None:
    file_id = FlexFieldFile.parse_reference(reference)
    if file_id is None:
        return None
    return reverse(FLEX_FILE_URL_NAME, args=[file_id])


def flex_file_src(value: Any) -> str:
    """Value usable as an `<img src>`, for references and legacy data-URIs alike."""
    if url := _flex_file_url(value):
        return url
    if isinstance(value, str) and value.startswith(DATA_URI_PREFIX):
        return value
    return ""


def _resolve_markers(
    record: "Validable",
    payload: Mapping[str, Any],
    files: Mapping[str, FlexFileContent],
    references: dict[str, str],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, value in payload.items():
        key = _parse_pending_marker(value)
        if key is None:
            continue
        if key not in references:
            if (item := files.get(key)) is None:
                resolved[name] = ""
                continue
            references[key] = write_flex_file(record, name, item.content, item.mimetype, item.filename)
        resolved[name] = references[key]
    return resolved


def _load_files(record: "Validable", file_ids: set[UUID]) -> dict[UUID, FlexFieldFile]:
    """Load the requested rows owned by `record`, prefetched ones included."""
    if PREFETCH_NAME in getattr(record, "_prefetched_objects_cache", {}):
        return {flex_file.pk: flex_file for flex_file in record.flex_field_files.all() if flex_file.pk in file_ids}
    files = FlexFieldFile.objects.with_content().filter(
        content_type=ContentType.objects.get_for_model(record, for_concrete_model=True),
        object_id=record.pk,
        pk__in=file_ids,
    )
    return {flex_file.pk: flex_file for flex_file in files}
